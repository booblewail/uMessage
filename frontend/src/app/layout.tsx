import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "uMessage",
  description: "One inbox across your Platforms, with plans spotted for your calendar.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
