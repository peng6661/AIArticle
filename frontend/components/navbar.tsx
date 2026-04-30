"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();
  const isDownloadPage = pathname === "/download";

  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-black/20 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex shrink-0 items-center gap-3 group">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#D94E28] shadow-md shadow-[#D94E28]/25 transition-transform group-hover:scale-[1.02]">
            <svg className="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
        </Link>

        <p className="pointer-events-none absolute left-1/2 -translate-x-1/2 text-sm font-semibold tracking-tight text-[#D94E28]/90">
          AIcreator
        </p>

        <div className="flex shrink-0 items-center">
          <Link
            href={isDownloadPage ? "/" : "/download"}
            className="btn-brand !px-5 !py-2.5 text-sm"
          >
            {isDownloadPage ? "转换模式" : "下载模式"}
          </Link>
        </div>
      </nav>
    </header>
  );
}
