import Link from "next/link";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  return (
    <aside className="flex w-60 flex-col border-r bg-muted/40">
      <div className="flex h-14 items-center px-4 font-semibold">
        ProposalCreation
      </div>
      <Separator />
      <nav className="flex flex-1 flex-col gap-1 p-3">
        <Link
          href="/"
          className="rounded-md px-3 py-2 text-sm hover:bg-accent"
        >
          案件一覧
        </Link>
        <Link
          href="/cases/new"
          className="rounded-md px-3 py-2 text-sm hover:bg-accent"
        >
          新規案件作成
        </Link>
        <Link
          href="/knowledge"
          className="rounded-md px-3 py-2 text-sm hover:bg-accent"
        >
          ナレッジ管理
        </Link>
      </nav>
    </aside>
  );
}
