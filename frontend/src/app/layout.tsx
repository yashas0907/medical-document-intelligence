import type { Metadata } from "next";
import { AuthProvider } from "@/components/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "MedIntel — Medical Document Intelligence",
  description:
    "Ingest, understand, summarize, compare, and query medical documents with full source provenance. Informational tool — not medical advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
