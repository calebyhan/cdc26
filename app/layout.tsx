import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Not My Debt — make the paperwork make sense",
  description:
    "A source-linked medical billing evidence workspace. Fictional presentation demo.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
