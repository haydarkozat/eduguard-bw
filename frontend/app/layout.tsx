import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EduGuard BW",
  description: "Self-hosted school IT monitoring & AI triage",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
