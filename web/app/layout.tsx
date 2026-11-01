import type { Metadata } from "next";
import { IBM_Plex_Mono, Public_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "../components/theme";

const publicSans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Onya: Your borrower passed. Barely.",
  description:
    "Onya finds what the compliance certificate glosses over: add-backs past the cap, savings still waiting on approval, and the quarter it breaks.",
  icons: {
    icon: "/favicon.svg",
    apple: "/brand/onya-app-icon.svg",
  },
  openGraph: {
    title: "Onya: Your borrower passed. Barely.",
    description:
      "Onya finds what the compliance certificate glosses over: add-backs past the cap, savings still waiting on approval, and the quarter it breaks.",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Onya: Covenant monitoring for private credit",
      },
      { url: "/brand/onya-app-icon.svg", alt: "Onya" },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Onya: Your borrower passed. Barely.",
    description:
      "Onya finds what the compliance certificate glosses over: add-backs past the cap, savings still waiting on approval, and the quarter it breaks.",
    images: ["/og-image.png"],
  },
};

const themeInit = `(function(){try{var t=localStorage.getItem("onya-theme");var d=t?t==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.classList.toggle("dark",d);}catch(e){document.documentElement.classList.toggle("dark",window.matchMedia("(prefers-color-scheme: dark)").matches);}})();`;

export default function RootLayout({
  children,
}: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${publicSans.variable} ${sourceSerif.variable} ${plexMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="flex min-h-full flex-col">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
