"""joseph -> discord bot.

exposes the deterministic osint engine as slash commands:

    /joseph dork        -> generate a ranked query family (no network)
    /joseph investigate -> run the full pipeline and return an intelligence report
    /joseph help        -> what joseph is and how to use it

designed to run as a railway worker: `python -m joseph.bot`.
"""

from __future__ import annotations

import io
import sys

import discord
from discord import app_commands

from .config import Config
from .engine.pipeline import investigate as run_investigate, plan_only
from .engine.seed import IdentitySeed
from .report.model import build_dataset
from .report.render import render_markdown

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
            value="generate a ranked query family from what you know. no network calls.",
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

    @joseph.command(name="dork", description="generate a ranked query family for a subject")
    @app_commands.describe(
        name="full name of the subject",
        usernames="known usernames / handles (comma separated)",
        emails="known emails (comma separated)",
        organizations="known organizations (comma separated)",
        locations="known locations (comma separated)",
        occupations="known occupations / roles (comma separated)",
        domains="known domains (comma separated)",
        sites="explicit site targets, name or domain (comma separated)",
        filetypes="document filetypes to hunt (comma separated, default pdf,doc,...)",
        exclusions="terms to exclude (comma separated)",
        since="earliest date YYYY or YYYY-MM or YYYY-MM-DD",
        until="latest date YYYY or YYYY-MM or YYYY-MM-DD",
        top="how many top queries to show inline (default 12)",
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
        filetypes: str = "",
        exclusions: str = "",
        since: str = "",
        until: str = "",
        top: int = 12,
    ) -> None:
        seed = _seed_from_options(
            name=name, usernames=usernames, emails=emails, organizations=organizations,
            locations=locations, occupations=occupations, domains=domains, sites=sites,
            filetypes=filetypes, exclusions=exclusions, since=since, until=until,
        )
        if seed.is_empty:
            await interaction.response.send_message(
                "give me at least one identifier -> name, username, email, or domain.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        inv = plan_only(seed)
        top = max(1, min(top, 25))

        header = (
            f"**joseph** -> {inv.query_count} queries ranked for "
            f"`{seed.name or seed.usernames[0] if seed.usernames else 'subject'}`. top {top}:\n"
        )
        body_lines = []
        for i, p in enumerate(inv.plans[:top], start=1):
            body_lines.append(f"{i}. `{p.query.render('google')}`  (score {p.scored.score:.2f})")
            body_lines.append(f"    <{p.urls['google']}>")
        body = header + "\n".join(body_lines)

        # full plan as an attached file
        full = "\n".join(
            f"{i}. [{p.scored.score:.2f}] {p.query.strategy}\n"
            f"   google: {p.query.render('google')}\n"
            f"   bing:   {p.query.render('bing')}\n"
            f"   ddg:    {p.query.render('ddg')}\n"
            f"   url:    {p.urls['google']}\n"
            for i, p in enumerate(inv.plans, start=1)
        )
        file = discord.File(io.BytesIO(full.encode("utf-8")), filename=f"joseph_dorks_{seed.fingerprint()}.txt")

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
