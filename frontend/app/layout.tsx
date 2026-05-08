import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import HotSearchShelf from "@/components/hot-search-shelf";
import "./globals.css";

const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AIcreator - 短视频转微信公众号文章自动化系统",
  description: "将短视频链接转化为高质量微信公众号文章的全自动化平台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh" className={sans.variable}>
      <body className={`${sans.className} font-sans antialiased`}>
        {children}
        <HotSearchShelf />
      </body>
    </html>
  );
}
