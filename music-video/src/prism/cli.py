"""Prism CLI."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from .audio.analyze import analyze
from .assembly.render import render, write_directors_notes
from .director.plan import plan_edit
from .vision.ingest import ingest_folder
from .vision.tag import tag_all

app = typer.Typer(
    add_completion=False,
    help="Prism — Claude Opus 4.7 as your music-video editor.",
)
console = Console()


def _banner() -> None:
    console.print(
        Panel.fit(
            "[bold magenta]PRISM[/bold magenta] — Claude Opus 4.7 as your music-video editor",
            border_style="magenta",
        )
    )


@app.command()
def cut(
    song: Path = typer.Option(..., exists=True, readable=True, help="Path to a copyright-free song."),
    clips: Path = typer.Option(..., exists=True, file_okay=False, help="Folder of video clips and/or images."),
    out: Path = typer.Option(Path("./out"), help="Output directory."),
    aspect: str = typer.Option("both", help="16:9, 9:16, or both."),
    cache: Path = typer.Option(Path(".prism-cache"), help="Cache directory."),
    dry: bool = typer.Option(False, "--dry", help="Skip Claude; round-robin clips. Fast smoke test, no tokens."),
) -> None:
    """Analyze, plan, and render a beat-matched music video."""
    _banner()

    if not dry and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY env var is required (or pass --dry to skip Claude).[/red]")
        raise typer.Exit(1)

    aspect = aspect.lower()
    if aspect not in {"16:9", "9:16", "both"}:
        console.print("[red]--aspect must be 16:9, 9:16, or both[/red]")
        raise typer.Exit(2)
    aspects = ["16:9", "9:16"] if aspect == "both" else [aspect]

    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    # 1. Audio
    with console.status("[cyan]Analyzing song (librosa)…"):
        grid = analyze(str(song))
    console.print(
        f"[green]♫[/green]  {Path(song).name}: "
        f"[bold]{grid.tempo:.0f} BPM[/bold], "
        f"{len(grid.beats)} beats, {len(grid.sections)} sections, {grid.duration:.1f}s"
    )

    # 2. Clip probe
    with console.status("[cyan]Probing clips (ffprobe + opencv)…"):
        profiles = ingest_folder(str(clips), str(cache))
    console.print(f"[green]🎞[/green]  {len(profiles)} clips probed")

    # 3. Claude vision tagging (or stub in --dry)
    if dry:
        from .models import ClipTags
        tags = [
            ClipTags(
                clip_id=p.clip_id, mood="neutral",
                energy=5 + int(p.motion_energy * 5),
                motion_type="subtle" if p.motion_energy < 0.02 else "tracking",
                subject="(dry-mode stub)",
                best_use="anywhere",
                directors_note="dry mode — no Claude call",
            )
            for p in profiles
        ]
        console.print("[yellow]⚠[/yellow]  [dim]dry mode: skipped Claude vision tagging[/dim]")
    else:
        with console.status("[cyan]Claude Opus 4.7 reading clips (vision)…"):
            tags = tag_all(profiles, str(cache))
        console.print(f"[green]🧠[/green]  {len(tags)} clips tagged by Opus 4.7")
    for t in tags[:3]:
        console.print(
            f"   [dim]{t.clip_id[:8]}[/dim]  "
            f"[bold]{t.mood}[/bold] · e{t.energy} · {t.motion_type} · {t.best_use}\n"
            f"      [italic]\"{t.directors_note}\"[/italic]"
        )
    if len(tags) > 3:
        console.print(f"   [dim](…{len(tags) - 3} more)[/dim]")

    # 4 & 5. Plan + render per aspect
    for a in aspects:
        console.rule(f"[bold cyan]→ {a}")
        if dry:
            from .models import EditPlan, EditSegment
            tag_ids = [t.clip_id for t in tags]
            segs: list[EditSegment] = []
            last = None
            for i in range(len(grid.beats) - 1):
                cid = tag_ids[i % len(tag_ids)]
                if cid == last and len(tag_ids) > 1:
                    cid = tag_ids[(i + 1) % len(tag_ids)]
                bs, be = grid.beats[i], grid.beats[i + 1]
                segs.append(EditSegment(
                    clip_id=cid, source_start=0.0, source_end=be - bs,
                    beat_start=bs, beat_end=be, cut_style="hard",
                    reasoning="dry mode — round-robin",
                ))
                last = cid
            plan = EditPlan(
                song_path=str(song), aspect=a, segments=segs,
                directors_note="[dry mode] Round-robin — run without --dry to get Claude's actual edit.",
            )
        else:
            with console.status(f"[cyan]Claude Opus 4.7 directing the edit ({a})…"):
                plan = plan_edit(grid, tags, aspect=a)
        console.print(f"[green]🎬[/green]  Plan: {len(plan.segments)} cuts")
        console.print(
            Panel(
                plan.directors_note or "[dim]no overall note[/dim]",
                title="[bold]Claude's director's note[/bold]",
                border_style="magenta",
            )
        )

        suffix = a.replace(":", "x")
        out_video = out / f"{song.stem}__{suffix}.mp4"
        out_notes = out / f"{song.stem}__{suffix}__director.json"
        with console.status(f"[cyan]Rendering {out_video.name} (ffmpeg)…"):
            render(
                plan, profiles, str(song), str(out_video),
                work_dir=str(cache / f"render_{suffix}"),
            )
            write_directors_notes(plan, str(out_notes))
        console.print(f"[green]✅[/green]  {out_video}")
        console.print(f"[green]📓[/green]  {out_notes}")

    console.rule("[bold green]Done.")
    console.print(f"[bold]Outputs:[/bold] {out}")


@app.command()
def version() -> None:
    """Print Prism version."""
    from . import __version__
    console.print(f"prism {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
