import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

const base = process.env.NEXT_PUBLIC_BASE_PATH || "";
export const metadata: Metadata = {
  title: "GrowthCognix — Growth intelligence for agencies",
  description: "Multi-tenant AI business growth and marketing intelligence platform.",
  icons: { icon: `${base}/icon.png` },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head><link rel="preconnect" href="https://fonts.googleapis.com" /><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" /></head>
      <body><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
