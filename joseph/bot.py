"""joseph -> discord bot.

exposes the deterministic osint engine as slash commands:

    /joseph dork        -> generate a ranked query family (no network)
    /joseph investigate -> run the full pipeline and return an intelligence report
    /joseph help        -> what joseph is and how to use it

designed to run as a railway worker: `python -m joseph.bot`.
"""

from __future__ import annotations

import io
import json
import sys

import discord
from discord import app_commands

from .config import Config
from .engine import providers
from .engine.pipeline import investigate as run_investigate, plan_only
from .engine.seed import IdentitySeed, filetypes_for_profile
from .report.model import build_dataset
from .report.render import render_markdown
from .shepherd.pattern_engine import select_patterns
from .shepherd.router import domain_names
from .vision.engine import analyze_image

INTRO = (
    "joseph is a deterministic (non-ai) osint query synthesis and evidence correlation "
    "engine. it turns what you know about a subject into a ranked family of search queries, "
    "and (optionally) collects, correlates, and reports on public results.\n\n"
    "boundary: public sources and documented search operators only. no auth bypass, no "
    "private-account access, no restricted records."
)


def _seed_from_options(**kwargs) -> IdentitySeed:
    return IdentitySeed.build(**kwargs)


def _chunk(text: str, size: int = 1900) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


class JosephClient(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()  # slash commands need no privileged intents
        super().__init__(intents=intents)
        self.config = config
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        register_commands(self.tree, self.config)
        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        who = self.user
        print(f"joseph online as {who} (id {getattr(who, 'id', '?')})", flush=True)


def register_commands(tree: app_commands.CommandTree, config: Config) -> None:
    joseph = app_commands.Group(name="joseph", description="deterministic osint query synthesis + evidence correlation")

    @joseph.command(name="help", description="what joseph is and how to use it")
    async def help_cmd(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="joseph", description=INTRO, color=0x0B7285)
        embed.add_field(
            name="/joseph dork",
            value=(
                "run the dorks and return the **direct working links** to what was found "
                "(not google search-result pages). pick a `filetype_profile` "
                "(documents / leaks / all) — you don't need to know extensions."
            ),
            inline=False,
        )
        embed.add_field(
            name="/joseph investigate",
            value=(
                "run the full pipeline -> queries, correlation, evidence graph, confidence, "
                "and an ASHERIN INTELLIGENCE AGENCY report. "
                f"live collection is currently **{'on' if config.live_search else 'off'}**."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @joseph.command(name="dork", description="run dorks and return the DIRECT working links (not search-result pages)")
    @app_commands.describe(
        name="full name of the subject",
        usernames="known usernames / handles (comma separated)",
        emails="known emails (comma separated)",
        organizations="known organizations (comma separated)",
        locations="known locations (comma separated)",
        occupations="known occupations / roles (comma separated)",
        domains="known domains (comma separated)",
        sites="explicit site targets, name or domain (comma separated)",
        filetype_profile="which filetypes the dork logic hunts (you don't need to know extensions)",
        filetypes="OPTIONAL override: exact filetypes (comma separated). leave blank to use the profile.",
        exclusions="terms to exclude (comma separated)",
        since="earliest date YYYY or YYYY-MM or YYYY-MM-DD",
        until="latest date YYYY or YYYY-MM or YYYY-MM-DD",
        verify="check each link actually resolves and drop dead ones (default true)",
        top="how many links to show inline (default 15)",
    )
    @app_commands.choices(
        filetype_profile=[
            app_commands.Choice(name="documents (pdf, doc, ppt, xls, txt)", value="documents"),
            app_commands.Choice(name="leaks (sql, env, log, csv, json, conf, bak, ...)", value="leaks"),
            app_commands.Choice(name="all (documents + leaks)", value="all"),
        ]
    )
    async def dork_cmd(
        interaction: discord.Interaction,
        name: str = "",
        usernames: str = "",
        emails: str = "",
        organizations: str = "",
        locations: str = "",
        occupations: str = "",
        domains: str = "",
        sites: str = "",
        filetype_profile: app_commands.Choice[str] = None,
        filetypes: str = "",
        exclusions: str = "",
        since: str = "",
        until: str = "",
        verify: bool = True,
        top: int = 15,
    ) -> None:
        profile = filetype_profile.value if filetype_profile else "documents"
        # explicit filetypes override the profile; otherwise the logic picks them for you
        resolved_filetypes = filetypes.strip() or ",".join(filetypes_for_profile(profile))

        seed = _seed_from_options(
            name=name, usernames=usernames, emails=emails, organizations=organizations,
            locations=locations, occupations=occupations, domains=domains, sites=sites,
            filetypes=resolved_filetypes, exclusions=exclusions, since=since, until=until,
        )
        if seed.is_empty:
            await interaction.response.send_message(
                "give me at least one identifier -> name, username, email, or domain.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        inv = plan_only(seed)
        top = max(1, min(top, 25))
        subject = seed.name or (seed.usernames[0] if seed.usernames else "subject")

        # execute the top dorks and collect the DIRECT destination links (ddg html endpoint
        # returns real result urls; we unwrap ddg redirects to the true target).
        max_q = min(max(config.max_live_queries, 10), 14)
        raws = await providers.collect_live(
            inv.plans, max_queries=max_q, timeout=config.http_timeout, pause_seconds=0.8
        )

        # dedupe by url, keep the first dork + title that surfaced it
        seen: set[str] = set()
        results = []
        for r in raws:
            if r.url in seen:
                continue
            seen.add(r.url)
            results.append(r)

        if not results:
            # live collection returned nothing (blocked / no organic results). fall back to
            # giving the ready-to-run search urls so the run is never empty.
            lines = [
                f"**joseph** -> live collection returned no direct links for `{subject}` "
                f"(the search endpoint may be rate-limiting). here are the ready-to-run dorks "
                f"(profile: **{profile}**):\n"
            ]
            for i, p in enumerate(inv.plans[:top], start=1):
                lines.append(f"{i}. `{p.query.render('google')}`\n    <{p.urls['google']}>")
            for c in _chunk("\n".join(lines)):
                await interaction.followup.send(content=c)
            return

        # verify links resolve, so we return WORKING links, not dead search hits
        working_map: dict[str, bool] = {}
        if verify:
            working_map = await providers.verify_links(
                [r.url for r in results][:40], timeout=config.http_timeout
            )
        # working first, then the rest, preserving rank order within each group
        results.sort(key=lambda r: (0 if working_map.get(r.url, not verify) else 1, r.rank))

        working_count = sum(1 for r in results if working_map.get(r.url, not verify))
        header = (
            f"**joseph** -> {len(results)} direct links for `{subject}` "
            f"(profile: **{profile}**"
            + (f", {working_count} verified reachable" if verify else "")
            + "):\n"
        )
        body_lines = []
        for i, r in enumerate(results[:top], start=1):
            mark = "" if not verify else ("✅ " if working_map.get(r.url) else "⚠️ ")
            title = (r.title or r.url)[:90]
            body_lines.append(f"{i}. {mark}[{title}]({r.url})")
            body_lines.append(f"    ↳ found by `{r.strategy}`")
        body = header + "\n".join(body_lines)

        payload = {
            "subject": subject,
            "filetype_profile": profile,
            "filetypes": seed.filetypes,
            "verified": verify,
            "count": len(results),
            "working_count": working_count,
            "links": [
                {
                    "url": r.url,
                    "title": r.title,
                    "snippet": r.snippet,
                    "found_by": r.strategy,
                    "query": r.query,
                    "provider": r.provider,
                    "working": working_map.get(r.url, None if not verify else False),
                }
                for r in results
            ],
        }
        file = discord.File(
            io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")),
            filename=f"joseph_links_{seed.fingerprint()}.json",
        )

        chunks = _chunk(body)
        await interaction.followup.send(content=chunks[0], file=file)
        for extra in chunks[1:]:
            await interaction.followup.send(content=extra)

    @joseph.command(name="investigate", description="run the full deterministic pipeline and return a report")
    @app_commands.describe(
        name="full name of the subject",
        usernames="known usernames / handles (comma separated)",
        emails="known emails (comma separated)",
        organizations="known organizations (comma separated)",
        locations="known locations (comma separated)",
        occupations="known occupations / roles (comma separated)",
        domains="known domains (comma separated)",
        sites="explicit site targets (comma separated)",
        keywords="free context keywords (comma separated)",
        exclusions="terms to exclude (comma separated)",
        since="earliest date YYYY / YYYY-MM / YYYY-MM-DD",
        until="latest date YYYY / YYYY-MM / YYYY-MM-DD",
    )
    async def investigate_cmd(
        interaction: discord.Interaction,
        name: str = "",
        usernames: str = "",
        emails: str = "",
        organizations: str = "",
        locations: str = "",
        occupations: str = "",
        domains: str = "",
        sites: str = "",
        keywords: str = "",
        exclusions: str = "",
        since: str = "",
        until: str = "",
    ) -> None:
        seed = _seed_from_options(
            name=name, usernames=usernames, emails=emails, organizations=organizations,
            locations=locations, occupations=occupations, domains=domains, sites=sites,
            keywords=keywords, exclusions=exclusions, since=since, until=until,
        )
        if seed.is_empty:
            await interaction.response.send_message(
                "give me at least one identifier -> name, username, email, or domain.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        inv = await run_investigate(
            seed,
            live=config.live_search,
            max_live_queries=config.max_live_queries,
            http_timeout=config.http_timeout,
        )
        dataset = build_dataset(inv)
        markdown = render_markdown(dataset)
        json_text = dataset.to_json()

        a = dataset
        embed = discord.Embed(
            title=f"{a.agency} -> intelligence assessment",
            description=a.executive_assessment,
            color=0x0B7285,
        )
        embed.add_field(name="report id", value=f"`{a.report_id}`", inline=True)
        embed.add_field(name="mode", value=a.methodology.get("mode", "?"), inline=True)
        embed.add_field(
            name="confidence",
            value=f"{a.overall_band} ({a.overall_confidence:.2f})",
            inline=True,
        )
        embed.add_field(name="queries", value=str(len(inv.plans)), inline=True)
        embed.add_field(name="sources", value=str(len(inv.results)), inline=True)
        embed.add_field(name="findings", value=str(len(a.findings)), inline=True)
        embed.set_footer(text=f"joseph v{a.engine_version} · non-ai · seed {a.seed_fingerprint}")

        md_file = discord.File(io.BytesIO(markdown.encode("utf-8")), filename=f"{a.report_id}.md")
        json_file = discord.File(io.BytesIO(json_text.encode("utf-8")), filename=f"{a.report_id}.json")

        await interaction.followup.send(embed=embed, files=[md_file, json_file])

    @joseph.command(name="route", description="show how shepherd routes a subject -> task type, domains, patterns")
    @app_commands.describe(
        name="full name", usernames="usernames", emails="emails",
        domains="domains", organizations="organizations",
    )
    async def route_cmd(
        interaction: discord.Interaction,
        name: str = "",
        usernames: str = "",
        emails: str = "",
        domains: str = "",
        organizations: str = "",
    ) -> None:
        seed = _seed_from_options(
            name=name, usernames=usernames, emails=emails, domains=domains, organizations=organizations
        )
        if seed.is_empty:
            await interaction.response.send_message(
                "give me at least one identifier so shepherd can classify the task.", ephemeral=True
            )
            return
        r, applied = select_patterns(seed)
        embed = discord.Embed(
            title="shepherd -> routing",
            description=f"task type: **{r.task_type}**",
            color=0x5F3DC4,
        )
        embed.add_field(name="domains", value="\n".join(domain_names(r.domains)) or "-", inline=False)
        embed.add_field(
            name="patterns applied",
            value="\n".join(
                f"`{p.pattern.id}@{p.pattern.version}` [{p.pattern.status}] "
                f"{'ok' if p.satisfied else 'queued'}"
                for p in applied
            ) or "none",
            inline=False,
        )
        embed.set_footer(text="deterministic table-driven routing · no ai")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @joseph.command(name="vision", description="visual/geo osint on an image (exif+gps + provenance; no biometric surveillance)")
    @app_commands.describe(image="an image to analyze (exif gps, provenance)")
    async def vision_cmd(interaction: discord.Interaction, image: discord.Attachment) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await image.read()
        except Exception:
            await interaction.followup.send("could not read the attachment.")
            return
        ev = analyze_image(data)

        embed = discord.Embed(title="joseph -> visual osint evidence", color=0x0B7285)
        for c in ev.channels:
            summary = c.status
            o = c.observations
            if c.channel == "exif_geo" and c.status == "resolved" and "gps" in o:
                g = o["gps"]
                summary = f"gps {g['lat']}, {g['lon']}"
            elif c.channel == "provenance" and c.status == "resolved":
                summary = f"{o.get('format', '?')} · {o.get('size_bytes', 0)} bytes · sha256 {str(o.get('sha256',''))[:12]}…"
            elif c.channel == "image" and c.status == "resolved":
                shot = " · likely screenshot" if o.get("likely_screenshot") else ""
                summary = f"{o.get('width')}x{o.get('height')} {o.get('format')} · {o.get('megapixels')}mp{shot}"
            elif c.channel == "phash" and c.status == "resolved":
                summary = f"phash `{o.get('phash')}` · dhash `{o.get('dhash')}` (compare with hamming distance)"
            elif c.channel == "face_detection" and c.status in ("resolved", "partial"):
                summary = f"{o.get('count', 0)} face(s) detected · sharpness {o.get('image_sharpness')} (measurement only, no identity)"
            elif c.reason:
                summary = f"{c.status} -> {c.reason}"
            embed.add_field(name=c.channel, value=summary[:1000], inline=False)
        if ev.location_hypothesis:
            lh = ev.location_hypothesis
            embed.add_field(
                name="location hypothesis",
                value=f"{lh['lat']}, {lh['lon']} ({lh['source']})\n{lh['caveat']}",
                inline=False,
            )
        embed.set_footer(text="visual similarity is a lead, not proof of identity · biometric channels disabled")

        import json as _json
        payload = _json.dumps(ev.to_dict(), indent=2, ensure_ascii=False)
        vfile = discord.File(io.BytesIO(payload.encode("utf-8")), filename="joseph_vision.json")
        await interaction.followup.send(embed=embed, file=vfile)

    @joseph.command(name="workspace", description="create a private research workspace (category + channels) for you")
    @app_commands.describe(
        name="a name for your case / workspace",
        private="only you and admins can see it (default true)",
    )
    async def workspace_cmd(interaction: discord.Interaction, name: str, private: bool = True) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("run this in a server, not a dm.", ephemeral=True)
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "i need the **Manage Channels** permission to create a workspace. ask an admin to grant it.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        safe = name.strip()[:90] or "case"
        category_name = f"joseph · {safe}"

        overwrites = None
        if private:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
        try:
            category = await guild.create_category(category_name, overwrites=overwrites, reason=f"joseph workspace for {interaction.user}")
            created = []
            for chan in ("case-file", "queries", "findings", "sources", "media"):
                ch = await category.create_text_channel(chan, reason="joseph workspace channel")
                created.append(ch.mention)
        except discord.Forbidden:
            await interaction.followup.send(
                "discord refused the operation -> check my role is high enough and has Manage Channels.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"discord error creating the workspace: {exc}", ephemeral=True)
            return

        visibility = "private (only you + admins)" if private else "public"
        await interaction.followup.send(
            f"created **{category_name}** ({visibility}) with channels: {', '.join(created)}",
            ephemeral=True,
        )

    tree.add_command(joseph)


def main() -> int:
    config = Config.load()
    if not config.has_token:
        print(
            "error: DISCORD_TOKEN is not set. copy .env.example to .env and set your bot token, "
            "or set it as a railway service variable.",
            file=sys.stderr,
        )
        return 1
    client = JosephClient(config)
    client.run(config.discord_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
