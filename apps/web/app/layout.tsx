import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Checkout",
  description: "Policy-guarded Solana stablecoin checkout agent",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
