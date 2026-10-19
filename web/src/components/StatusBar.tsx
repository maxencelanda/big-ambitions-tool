import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ServerEvent } from "../api";
import { ago, gameDate, money } from "../format";

const EVENT_TEXT: Record<string, (e: ServerEvent) => string> = {
  change_detected: (e) => `Save changed: ${e.save}`,
  import_started: (e) => `Importing ${e.save}…`,
  import_done: (e) => `Imported ${e.save} (day ${e.day} ${e.time}, ${e.seconds}s)`,
  import_retry: (e) => `Waiting for the game to finish writing ${e.save}`,
  import_failed: (e) => `Import failed: ${e.error}`,
  job_started: (e) => `${JOB_LABEL[e.job as string] ?? e.job} started…`,
  job_done: (e) => `${JOB_LABEL[e.job as string] ?? e.job} done`,
  job_failed: (e) => `${JOB_LABEL[e.job as string] ?? e.job} failed: ${e.error}`,
  watch_changed: (e) => (e.watching ? "Watching saves" : "Stopped watching saves"),
};
const JOB_LABEL: Record<string, string> = { sync: "Sync", gamedata: "Game data extraction", check: "biggerambitions check" };

function saveName(save: string | undefined) {
  return save?.split("/").pop() ?? "—";
}

export function StatusBar({ lastEvent }: { lastEvent: ServerEvent | null }) {
  const queryClient = useQueryClient();
  const { data: status, error } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 30_000 });
  const onSettled = () => queryClient.invalidateQueries({ queryKey: ["status"] });
  const sync = useMutation({ mutationFn: (force: boolean) => api.sync(force), onSettled });
  const gamedata = useMutation({ mutationFn: api.refreshGamedata, onSettled });
  const check = useMutation({ mutationFn: () => api.checkBiggerAmbitions(true), onSettled });
  const watch = useMutation({ mutationFn: api.setWatch, onSettled });

  if (error) {
    return <div className="statusbar"><span className="pill"><span className="dot err" />API unreachable — is <code>app.py</code> running?</span></div>;
  }
  if (!status) return <div className="statusbar"><span className="pill">Loading…</span></div>;

  const source = status.source;
  const running = (job: string) => job in status.jobs;
  const busy = status.busy || running("sync");
  const mutationError = [sync, gamedata, check, watch].find((m) => m.error)?.error as Error | undefined;
  const failed = lastEvent?.type.endsWith("failed") || Boolean(mutationError);
  const eventText = mutationError ? mutationError.message : lastEvent ? EVENT_TEXT[lastEvent.type]?.(lastEvent) : null;
  const reference = status.reference;

  return (
    <div className="statusbar">
      <div className="source">
        <strong>{source ? `${saveName(source.save)} · ${gameDate(source.day)} · ${source.time}` : "No save imported yet"}</strong>
        <span>
          {source ? `Imported ${ago(source.importedAt)} · ${money(source.money, { compactForm: false })} cash` : status.saveRoot}
        </span>
      </div>

      <span className="pill" title={status.pending ? `Waiting for ${status.pending} to settle` : undefined}>
        <span className={`dot ${busy ? "busy" : status.watching ? "on" : ""}`} />
        {busy ? "Importing" : status.pending ? "Change detected" : status.watching ? "Watching" : "Not watching"}
      </span>
      {!reference.available && <span className="pill"><span className="dot err" />Game data missing</span>}
      {reference.stale && <span className="pill"><span className="dot warn" />Game updated — refresh game data</span>}
      {status.lastError && <span className="pill" title={status.lastError.error}><span className="dot warn" />Last read failed</span>}

      {eventText && <span className={`toast ${failed ? "err" : ""}`} title={eventText}>{eventText}</span>}
      <span className="spacer" />

      <div className="actions">
        <label className="toggle">
          <input type="checkbox" checked={status.watching} disabled={watch.isPending}
                 onChange={(e) => watch.mutate(e.target.checked)} />
          Auto-sync
        </label>
        <button className="btn primary" disabled={busy}
                title="Import the latest save now (Shift+click: force re-import)"
                onClick={(e) => sync.mutate(e.shiftKey)}>
          {busy ? "Syncing…" : "Sync now"}
        </button>
        <button className="btn" disabled={running("gamedata")}
                title={`Re-extract prices, buildings and neighborhoods from the game files${reference.version?.extractedAt ? ` (last: ${reference.version.extractedAt})` : ""}`}
                onClick={() => gamedata.mutate()}>
          {running("gamedata") ? "Extracting…" : "Refresh game data"}
        </button>
        <button className="btn" disabled={running("check") || !reference.available}
                title={status.checks ? `Last check ${ago(status.checks.checkedAt)}: ${Object.entries(status.checks.byStatus).map(([k, v]) => `${k} ${v}`).join(", ")}` : "Compare biggerambitions.com with the game data"}
                onClick={() => check.mutate()}>
          {running("check") ? "Checking…" : "Check biggerambitions"}
        </button>
      </div>
    </div>
  );
}
