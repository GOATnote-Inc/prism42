import { DispatcherShellB300 } from "@/components/DispatcherShellB300";
import { modeFromSearchParams } from "@/lib/mode";

export const metadata = {
  title: "prism42-b300 live — B300 augmented console",
};

/**
 * Live console at /prism42-b300/live. The `?mode=` query string controls
 * which rubric-grader path the client calls. Defaults to `vercel` (identical
 * to the baseline /prism42 experience). `?mode=b300` routes the rubric grade
 * through the local Llama-3-70B NVFP4 endpoint on the B300 pod.
 *
 * Everything else (coordinator LLM, STT, TTS, prompts) is identical across
 * modes by design — the A/B experiment is single-variable per the approved
 * Phase 2-min plan.
 */
export default async function Prism42B300LivePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const mode = modeFromSearchParams(sp);
  return <DispatcherShellB300 mode={mode} />;
}
