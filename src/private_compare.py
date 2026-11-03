"""Private mode: compare a lender's certificate with Onya's recalculation.

Everything here runs in memory. Uploaded bytes, pasted text, and
extracted text are never written to disk, never stored in traces, never
logged (only sizes, timings, and status are logged), never included in
error messages, and never cached.
"""

import base64
import binascii
import io
import json
import logging
import os
import time

import model_calls

log = logging.getLogger("onya.private")

MODEL = "meta-models/muse-spark-open-1026"
MAX_UPLOAD_BYTES = 2_000_000
# Reasoning models spend thousands of tokens thinking before answering;
# the cap must leave room for the answer (same scale as extract_disclosed).
MAX_TOKENS = 16000
TEMPERATURE = 0
DEADLINE_SECONDS = 270

SAMPLE_NAME = "sample_certificate_snbr.txt"


class PrivateInputError(Exception):
    """Plain, content-free reason the upload was rejected."""


class PrivateUnavailable(Exception):
    """Baseten model access is not configured."""


def make_baseten_client():
    """OpenAI-compatible client for Muse Spark Open on Baseten."""
    from openai import OpenAI

    api_key = os.environ.get("BASETEN_API_KEY")
    base_url = os.environ.get("BASETEN_BASE_URL")
    if not api_key or not base_url:
        raise PrivateUnavailable(
            "private mode is unavailable (model not configured)")
    # No SDK retries: model_calls makes the one retry, and reports it.
    return OpenAI(api_key=api_key, base_url=base_url,
                  timeout=model_calls.PER_CALL_SECONDS, max_retries=0)


def sniff_kind(data):
    """'pdf', 'text', or 'unknown', judged by content only."""
    if not isinstance(data, (bytes, bytearray)):
        return "unknown"
    head = bytes(data[:8]).lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"%PDF"):
        return "pdf"
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return "unknown"
    if "\x00" in text:
        return "unknown"
    return "text" if text.strip() else "unknown"


def extract_pdf_text(data):
    """Text of a PDF upload, or a content-free PrivateInputError."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(bytes(data)))
    except Exception:
        raise PrivateInputError("unreadable PDF file")
    if reader.is_encrypted:
        raise PrivateInputError("encrypted PDF file")
    try:
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        raise PrivateInputError("unreadable PDF file")
    text = "\n".join(pages).strip()
    if not text:
        raise PrivateInputError("PDF has no extractable text")
    return text


def prepare_document(text=None, file_b64=None, filename=None):
    """Return (document_text, label) from paste or upload, in memory.

    Raises PrivateInputError with a content-free reason when the input
    is missing, ambiguous, oversized, or of an unknown type.
    """
    have_text = bool((text or "").strip())
    have_file = bool(file_b64)
    if have_text and have_file:
        raise PrivateInputError("send pasted text or a file, not both")
    if not have_text and not have_file:
        raise PrivateInputError("pasted text or a file is required")
    if have_text:
        raw = text.encode("utf-8")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise PrivateInputError(
                "pasted text exceeds %d bytes" % MAX_UPLOAD_BYTES)
        return text, "pasted text"
    try:
        raw = base64.b64decode(file_b64, validate=True)
    except (binascii.Error, ValueError):
        raise PrivateInputError("file is not valid base64")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PrivateInputError(
            "file exceeds %d bytes" % MAX_UPLOAD_BYTES)
    kind = sniff_kind(raw)
    if kind == "pdf":
        return extract_pdf_text(raw), filename or "uploaded PDF"
    if kind == "text":
        return raw.decode("utf-8"), filename or "uploaded text file"
    raise PrivateInputError("file must be a PDF or plain text")


CERT_PROMPT = """\
Extract the covenant figures reported in the compliance certificate below.
Return ONLY this JSON object, no markdown, no commentary:

{"covenants": [{"name": "...", "direction": "max" or "min",
"threshold": number or null, "actual": number or null,
"quote": "exact verbatim sentence with the figure"}],
"components": [{"name": "...", "value": number,
"quote": "exact verbatim sentence with the figure"}]}

Rules: every quote must be copied verbatim from the certificate text
above (max 40 words each), with original punctuation. Copy each
reported ratio, limit, and dollar component (total debt, EBITDA,
EBITDAR, interest expense, projected savings) exactly once. Numbers
only; omit anything the certificate does not state.

Certificate:
"""


def extract_certificate_figures(document_text, client, deadline=None,
                                on_retry=None, call_log=None):
    """Model extraction of reported figures, with quote verification.

    Returns (figures, usage_tokens). Each figure carries verified True
    only when its quote appears verbatim in the document; otherwise the
    figure is kept and marked unverified.
    """
    from extract_disclosed import normalize, quote_in_source

    response = model_calls.call(
        client, label="private_extract",
        deadline=deadline or model_calls.Deadline(DEADLINE_SECONDS),
        on_retry=on_retry, call_log=call_log,
        model=MODEL,
        messages=[{"role": "user",
                   "content": CERT_PROMPT + document_text}],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    raw = (response.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[: -3]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise PrivateInputError("model returned unusable output")
    usage = getattr(response, "usage", None)
    tokens = 0
    if usage is not None:
        tokens = (getattr(usage, "total_tokens", 0) or 0)
    source_norm = normalize(document_text)
    figures = {"covenants": [], "components": []}
    for covenant in (parsed.get("covenants") or []):
        if not isinstance(covenant, dict):
            continue
        figures["covenants"].append({
            "name": covenant.get("name"),
            "direction": covenant.get("direction"),
            "threshold": covenant.get("threshold"),
            "actual": covenant.get("actual"),
            "quote": covenant.get("quote"),
            "verified": quote_in_source(covenant.get("quote"),
                                        source_norm),
        })
    for component in (parsed.get("components") or []):
        if not isinstance(component, dict):
            continue
        figures["components"].append({
            "name": component.get("name"),
            "value": component.get("value"),
            "quote": component.get("quote"),
            "verified": quote_in_source(component.get("quote"),
                                        source_norm),
        })
    return figures, tokens


def _ratio_2dp(value):
    return round(float(value) + 0.0, 2)


def _governing_is_forbearance(slug, period_end):
    """True when the cached agreement selection is a forbearance.

    Uses the reporting-window cutoff (period_end + 45 days). Cached
    companies resolve from the bundled select cache; any miss or error
    means False.
    """
    import datetime

    import edgar

    try:
        end = datetime.date.fromisoformat(str(period_end)[:10])
        cutoff = (end + datetime.timedelta(days=45)).isoformat()
        base, _amendments = edgar.select_agreement(
            "SNBR" if slug == "snbr" else slug, as_of=cutoff,
            verbose=False)
        base = base or {}
        text = (str(base.get("title") or "") + " "
                + str(base.get("description") or "")).lower()
        return bool(base.get("is_forbearance")
                    or "forbearance" in text)
    except Exception:
        return False


def compare_with_onya(ticker, period_end, figures):
    """Side-by-side rows of certificate vs Onya, plus gap flags.

    Reads only the committed result files via the compute pipelines;
    raises PrivateInputError for an unsupported company or period.
    """
    import covenant
    import project

    slug = str(ticker or "").strip().lower()
    if slug not in ("snbr", "sleep number"):
        raise PrivateInputError("unsupported company for comparison")
    try:
        computed = covenant.compute(period_end)
    except Exception:
        raise PrivateInputError("no computed results for that period")
    try:
        projection = project.compute(period_end)
    except Exception:
        projection = {}

    onya = {}
    for key in ("net_leverage", "interest_coverage"):
        block = computed.get(key) or {}
        onya[key] = {"ratio": block.get("ratio_2dp"),
                     "threshold": block.get("threshold"),
                     "pass": block.get("pass")}
    pre_savings = None
    baseline = (projection.get("baseline") or {})
    if baseline.get("onya_pre_proforma") is not None:
        pre_savings = baseline.get("onya_pre_proforma")

    labels = {"net_leverage": "net leverage",
              "interest_coverage": "interest coverage"}
    rows = []
    flags = []
    for covenant_fig in (figures.get("covenants") or []):
        name = str(covenant_fig.get("name") or "")
        lowered = name.lower()
        key = ("net_leverage" if "leverage" in lowered
               else "interest_coverage" if "coverage" in lowered
               else None)
        entry = {"name": name or "reported covenant",
                 "certificate": covenant_fig.get("actual"),
                 "threshold": covenant_fig.get("threshold"),
                 "verified": bool(covenant_fig.get("verified"))}
        if key is None or onya[key]["ratio"] is None:
            entry.update({"onya": None, "difference": None,
                          "explanation": "no matching Onya covenant"})
        else:
            diff = _ratio_2dp(covenant_fig.get("actual") or 0) \
                - _ratio_2dp(onya[key]["ratio"])
            entry.update({
                "onya": onya[key]["ratio"],
                "difference": round(diff, 2),
                "explanation": (
                    "matches Onya" if abs(diff) < 0.005
                    else "differs from Onya; see the gap summary"),
            })
        rows.append(entry)
        limit = onya.get(key, {}).get("threshold") \
            if key is not None else None
        actual = covenant_fig.get("actual")
        direction = str(covenant_fig.get("direction") or "").lower()
        if (limit is None or actual is None
                or not isinstance(actual, (int, float))):
            continue
        failed = (direction == "max" and actual > limit
                  or direction == "min" and actual < limit)
        if not failed:
            continue
        side = "above" if direction == "max" else "below"
        sentence = ("The certificate's %s of %.2fx is still %s the "
                    "%.2fx limit." % (labels[key], actual, side, limit))
        if _governing_is_forbearance(slug, period_end):
            sentence += (" Its compliance statement relies on the "
                         "forbearance, not the ratio.")
        flags.append(sentence)

    if (computed.get("disallowed") or 0) > 0:
        flags.append(
            "Add-backs above the shared cap: Onya disallowed $%s." %
            f"{computed['disallowed']:,}")
    cert_ebitda = None
    for component in (figures.get("components") or []):
        if "ebitda" in str(component.get("name") or "").lower() \
                and "ebitdar" not in str(component.get("name") or "") \
                .lower():
            cert_ebitda = component.get("value")
            break
    if cert_ebitda is not None and pre_savings is not None \
            and cert_ebitda > pre_savings:
        flags.append(
            "Certificate EBITDA of $%s exceeds Onya's pre-savings "
            "figure of $%s: the difference needs administrative "
            "agent approval before it counts." %
            (f"{cert_ebitda:,}", f"{pre_savings:,}"))

    summary = []
    differing = [r for r in rows if r.get("onya") is not None
                 and r.get("explanation", "").startswith("differs")]
    if not differing and not flags:
        summary.append("The certificate matches Onya's recalculation.")
    else:
        if differing:
            summary.append(
                "%d covenant(s) differ from Onya's recalculation." %
                len(differing))
        summary.extend(flags)
    started = time.time()
    log.info("compare built rows=%d flags=%d elapsed=%.2fs",
             len(rows), len(flags), time.time() - started)
    return {"ticker": str(ticker).upper(), "period_end": period_end,
            "rows": rows, "flags": flags,
            "summary": summary, "onya": onya}


def run_compare(ticker, period_end, text=None, file_b64=None,
                filename=None, client=None, on_retry=None, call_log=None):
    """Full pipeline in memory: prepare, extract, compare.

    Returns (result, usage_tokens, timings). Raises PrivateInputError
    or PrivateUnavailable with content-free messages.
    """
    started = time.time()
    document_text, label = prepare_document(
        text=text, file_b64=file_b64, filename=filename)
    log.info("compare input kind=%s bytes=%d", label, len(document_text))
    owned_client = False
    if client is None:
        client = make_baseten_client()
        owned_client = True
    try:
        figures, tokens = extract_certificate_figures(
            document_text, client, on_retry=on_retry, call_log=call_log)
    finally:
        if owned_client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass
    result = compare_with_onya(ticker, period_end, figures)
    result["figures"] = figures
    elapsed = time.time() - started
    log.info("compare done rows=%d tokens=%d elapsed=%.2fs",
             len(result["rows"]), tokens, elapsed)
    return result, tokens, {"elapsed": round(elapsed, 2)}
