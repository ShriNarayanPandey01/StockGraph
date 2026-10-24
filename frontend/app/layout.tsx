import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TRACK — Markets, mapped.",
  description: "Explore connected stock, news, event, and professional evidence with source context.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><head><link rel="preconnect" href="https://fonts.googleapis.com"/><link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous"/><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;450;500;550;600;650;700;750;800&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet"/></head><body>{children}</body></html>;
}
