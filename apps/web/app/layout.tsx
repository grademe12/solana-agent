import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Checkout — Policy-guarded Solana payments",
  description: "QR 결제 요청을 예산 정책 안에서 실행하고 온체인 영수증으로 검증합니다.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
