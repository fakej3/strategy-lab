import type { ReactNode } from "react";

export const metadata = {
  title: "Strategy Labs",
  description: "Quantitative research workspace",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#09090b", color: "#f4f4f5", fontFamily: "system-ui, sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
