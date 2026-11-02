import type { Metadata } from "next";
import "@excalidraw/excalidraw/index.css";
import "prismjs/themes/prism-tomorrow.css";
import "./globals.css";
import Providers from "./providers";

export const metadata: Metadata = {
  title: "Stress Architecture",
  description: "Design, simulate, and deploy resilient system architectures.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
