import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { istTime } from "@/lib/format";
import type { Notification } from "@/lib/types";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => apiGet<Notification[]>("/notifications?limit=25"),
    refetchInterval: 5000,
    retry: false,
  });
  const readAll = useMutation({
    mutationFn: () => apiPost<{ updated: number }>("/notifications/read-all"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const items = data ?? [];
  const unread = items.filter((n) => !n.read).length;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="relative grid size-8 place-items-center rounded-md border border-slate-800 bg-slate-900/60 text-slate-400 transition-colors duration-150 hover:border-slate-700 hover:text-slate-200"
            data-testid="notification-bell-button"
            aria-label="Notifications"
          >
            <Bell className="size-4" />
            {unread > 0 ? (
              <span
                className="absolute -right-1 -top-1 grid min-w-4 place-items-center rounded-full bg-sky-500 px-1 font-mono text-[9px] font-bold text-white"
                data-testid="notification-unread-count"
              >
                {unread}
              </span>
            ) : null}
          </button>
        }
      />
      <PopoverContent align="end" className="w-[360px] border-slate-800 bg-[#111722] p-0">
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
          <span className="font-heading text-xs font-semibold uppercase tracking-wider text-slate-400">
            Signal alerts
          </span>
          <Button
            size="xs"
            variant="ghost"
            onClick={() => readAll.mutate()}
            data-testid="notifications-mark-read-button"
          >
            Mark all read
          </Button>
        </div>
        <div className="max-h-[380px] overflow-y-auto" data-testid="notification-list">
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-slate-500" data-testid="notifications-empty">
              No alerts yet. New signals, target hits and stop-losses appear here.
            </p>
          ) : (
            items.map((n) => (
              <article
                key={n.id}
                className={`border-b border-slate-800/70 px-3 py-2.5 ${n.read ? "opacity-70" : ""}`}
                data-testid={`notification-item-${n.id}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs font-semibold text-slate-200">{n.title}</p>
                  <span className="shrink-0 font-mono text-[10px] text-slate-500">{istTime(n.ts)}</span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{n.body}</p>
              </article>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
