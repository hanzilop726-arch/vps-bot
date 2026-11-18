import os
import sqlite3
import secrets
import shlex
import socket
import asyncio
from pathlib import Path

import discord
import docker
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("DISCORD_TOKEN")
PUBLIC_IP = os.getenv("PUBLIC_IP")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

PORT_START = int(os.getenv("PORT_START", "20000"))
PORT_END = int(os.getenv("PORT_END", "30000"))
IMAGE_NAME = "minehosting-vps:latest"
DB_PATH = BASE_DIR / "vps.db"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

docker_client = docker.from_env()

db = sqlite3.connect(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS vps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    container_id TEXT NOT NULL,
    host_port INTEGER NOT NULL,
    ram_mb INTEGER NOT NULL,
    cpu_cores REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def get_vps(vps_id):
    return db.execute(
        "SELECT * FROM vps WHERE id = ?",
        (vps_id,)
    ).fetchone()


def get_container(row):
    if not row:
        return None
    try:
        return docker_client.containers.get(row[2])
    except docker.errors.NotFound:
        return None


def find_free_port():
    used = {
        row[0]
        for row in db.execute("SELECT host_port FROM vps").fetchall()
    }

    for port in range(PORT_START, PORT_END + 1):
        if port in used:
            continue

        sock = socket.socket()
        try:
            sock.bind(("0.0.0.0", port))
            return port
        except OSError:
            pass
        finally:
            sock.close()

    raise RuntimeError("No free SSH ports available.")


async def admin_check(interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Admin only command.",
            ephemeral=True
        )
        return False
    return True


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")
    print("MineHosting VPS Bot is online.")


@bot.tree.command(
    name="vps-create",
    description="Create a Docker VPS for a Discord user"
)
@app_commands.describe(
    user="VPS owner",
    ram_mb="RAM in MB (512-16384)",
    cpu_cores="CPU cores (0.5-8)"
)
async def vps_create(
    interaction: discord.Interaction,
    user: discord.User,
    ram_mb: int,
    cpu_cores: float
):
    if not await admin_check(interaction):
        return

    if not 512 <= ram_mb <= 16384:
        return await interaction.response.send_message(
            "RAM must be between 512 and 16384 MB.",
            ephemeral=True
        )

    if not 0.5 <= cpu_cores <= 8:
        return await interaction.response.send_message(
            "CPU must be between 0.5 and 8 cores.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    container = None

    try:
        docker_client.images.get(IMAGE_NAME)
        port = find_free_port()
        password = secrets.token_urlsafe(16)

        container = docker_client.containers.run(
            IMAGE_NAME,
            detach=True,
            name=f"minehosting-vps-{secrets.token_hex(5)}",
            ports={"22/tcp": port},
            mem_limit=f"{ram_mb}m",
            nano_cpus=int(cpu_cores * 1_000_000_000),
            pids_limit=256,
            restart_policy={"Name": "unless-stopped"},
            labels={"minehosting.owner": str(user.id)}
        )

        result = container.exec_run(
            [
                "/bin/bash",
                "-lc",
                f"printf '%s\\n' {shlex.quote('root:' + password)} | chpasswd"
            ],
            user="root"
        )

        if result.exit_code != 0:
            raise RuntimeError("Could not configure SSH password.")

        neofetch_result = container.exec_run(
            ["/bin/bash", "-lc", "apt update && apt install neofetch -y"],
            user="root"
        )

        if neofetch_result.exit_code != 0:
            raise RuntimeError("Neofetch installation failed.")

        cursor = db.execute(
            """INSERT INTO vps
            (owner_id, container_id, host_port, ram_mb, cpu_cores)
            VALUES (?, ?, ?, ?, ?)""",
            (user.id, container.id, port, ram_mb, cpu_cores)
        )
        db.commit()
        vps_id = cursor.lastrowid

        embed = discord.Embed(
            title="✅ VPS Created",
            color=discord.Color.green()
        )
        embed.add_field(name="VPS ID", value=f"#{vps_id}")
        embed.add_field(name="Owner", value=user.mention)
        embed.add_field(name="RAM", value=f"{ram_mb} MB")
        embed.add_field(name="CPU", value=f"{cpu_cores} cores")
        embed.add_field(
            name="SSH Command",
            value=f"`ssh root@{PUBLIC_IP} -p {port}`",
            inline=False
        )
        embed.add_field(name="Username", value="`root`")
        embed.add_field(name="Password", value=f"`{password}`", inline=False)
        embed.set_footer(text="Keep this password private.")

        try:
            await user.send(embed=embed)
            await interaction.followup.send(
                f"✅ VPS #{vps_id} created! SSH details sent to {user.mention} via DM.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ VPS created, but user DMs are closed. Private credentials fallback:",
                embed=embed,
                ephemeral=True
            )

    except Exception as e:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

        await interaction.followup.send(
            f"❌ VPS creation failed: {str(e)[:900]}",
            ephemeral=True
        )


@bot.tree.command(name="vps-start", description="Start a VPS")
async def vps_start(interaction: discord.Interaction, vps_id: int):
    if not await admin_check(interaction):
        return

    row = get_vps(vps_id)
    container = get_container(row)

    if not container:
        return await interaction.response.send_message(
            "VPS or container not found.", ephemeral=True
        )

    try:
        container.start()
        await interaction.response.send_message(
            f"✅ VPS #{vps_id} started.", ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ {str(e)[:900]}", ephemeral=True
        )


@bot.tree.command(name="vps-stop", description="Stop a VPS")
async def vps_stop(interaction: discord.Interaction, vps_id: int):
    if not await admin_check(interaction):
        return

    container = get_container(get_vps(vps_id))

    if not container:
        return await interaction.response.send_message(
            "VPS or container not found.", ephemeral=True
        )

    try:
        container.stop(timeout=10)
        await interaction.response.send_message(
            f"✅ VPS #{vps_id} stopped.", ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ {str(e)[:900]}", ephemeral=True
        )


@bot.tree.command(name="vps-restart", description="Restart a VPS")
async def vps_restart(interaction: discord.Interaction, vps_id: int):
    if not await admin_check(interaction):
        return

    container = get_container(get_vps(vps_id))

    if not container:
        return await interaction.response.send_message(
            "VPS or container not found.", ephemeral=True
        )

    try:
        container.restart(timeout=10)
        await interaction.response.send_message(
            f"✅ VPS #{vps_id} restarted.", ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ {str(e)[:900]}", ephemeral=True
        )


@bot.tree.command(name="vps-info", description="View VPS information")
async def vps_info(interaction: discord.Interaction, vps_id: int):
    if not await admin_check(interaction):
        return

    row = get_vps(vps_id)

    if not row:
        return await interaction.response.send_message(
            "VPS not found.", ephemeral=True
        )

    container = get_container(row)
    status = "Missing" if not container else container.status

    embed = discord.Embed(
        title=f"VPS #{row[0]}",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Owner ID", value=str(row[1]))
    embed.add_field(name="Status", value=status)
    embed.add_field(name="SSH Port", value=str(row[3]))
    embed.add_field(name="RAM", value=f"{row[4]} MB")
    embed.add_field(name="CPU", value=f"{row[5]} cores")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="vps-list", description="List all VPS containers")
async def vps_list(interaction: discord.Interaction):
    if not await admin_check(interaction):
        return

    rows = db.execute("SELECT * FROM vps ORDER BY id DESC").fetchall()

    if not rows:
        return await interaction.response.send_message(
            "No VPS found.", ephemeral=True
        )

    lines = []

    for row in rows[:20]:
        container = get_container(row)
        status = "Missing" if not container else container.status
        lines.append(
            f"#{row[0]} | Owner: {row[1]} | Port: {row[3]} | {status}"
        )

    await interaction.response.send_message(
        "```text\n" + "\n".join(lines) + "\n```",
        ephemeral=True
    )


@bot.tree.command(name="vps-delete", description="Delete a user's VPS")
async def vps_delete(
    interaction: discord.Interaction,
    user: discord.User,
    vps_id: int
):
    if not await admin_check(interaction):
        return

    row = get_vps(vps_id)

    if not row or row[1] != user.id:
        return await interaction.response.send_message(
            "VPS does not belong to this user.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        container = get_container(row)

        if container:
            container.remove(force=True)

        db.execute("DELETE FROM vps WHERE id = ?", (vps_id,))
        db.commit()

        await interaction.followup.send(
            f"✅ VPS #{vps_id} deleted.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"❌ Delete failed: {str(e)[:900]}",
            ephemeral=True
        )


@bot.tree.command(
    name="console",
    description="Run a command inside a user's VPS"
)
@app_commands.describe(
    user="VPS owner",
    vps_id="VPS database ID",
    command="Command to execute inside the VPS"
)
async def console(
    interaction: discord.Interaction,
    user: discord.User,
    vps_id: int,
    command: str
):
    if not await admin_check(interaction):
        return

    if not command.strip() or len(command) > 1000:
        return await interaction.response.send_message(
            "Command must contain 1-1000 characters.",
            ephemeral=True
        )

    row = get_vps(vps_id)

    if not row or row[1] != user.id:
        return await interaction.response.send_message(
            "VPS does not belong to this user.",
            ephemeral=True
        )

    container = get_container(row)

    if not container:
        return await interaction.response.send_message(
            "Container not found.",
            ephemeral=True
        )

    container.reload()

    if container.status != "running":
        return await interaction.response.send_message(
            "VPS is not running.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        result = await asyncio.to_thread(
            container.exec_run,
            [
                "/usr/bin/timeout",
                "30s",
                "/bin/bash",
                "-lc",
                command
            ],
            user="root",
            demux=True,
            tty=False
        )

        stdout, stderr = result.output
        output = (
            (stdout or b"").decode("utf-8", errors="replace")
            + (stderr or b"").decode("utf-8", errors="replace")
        )

        if not output.strip():
            output = "Command executed. No output."

        output = output.replace("```", "'''")[:850]

        embed = discord.Embed(
            title="🖥️ MineHosting Console",
            color=discord.Color.blurple()
        )
        embed.add_field(name="VPS", value=f"#{vps_id} • {user.mention}")
        embed.add_field(
            name="Command",
            value=f"```bash\n{command[:900]}\n```",
            inline=False
        )
        embed.add_field(
            name="Output",
            value=f"```text\n{output}\n```",
            inline=False
        )
        embed.add_field(name="Exit Code", value=str(result.exit_code))

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Console error: {str(e)[:900]}",
            ephemeral=True
        )


@bot.tree.command(
    name="sshx",
    description="Get an SSHX access link for a VPS"
)
@app_commands.describe(
    vps_id="VPS ID"
)
async def sshx(
    interaction: discord.Interaction,
    vps_id: int
):
    row = db.execute(
        "SELECT * FROM vps WHERE id = ? AND owner_id = ?",
        (vps_id, interaction.user.id)
    ).fetchone()

    if not row:
        return await interaction.response.send_message(
            f"❌ VPS #{vps_id} was not found or does not belong to you.",
            ephemeral=True
        )

    container = get_container(row)

    if not container:
        return await interaction.response.send_message(
            "❌ Your VPS container was not found.",
            ephemeral=True
        )

    container.reload()

    if container.status != "running":
        return await interaction.response.send_message(
            f"❌ VPS #{vps_id} is not running.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        check = container.exec_run(
            ["/bin/bash", "-lc", "command -v sshx"],
            user="root"
        )

        if check.exit_code != 0:
            install = container.exec_run(
                [
                    "/bin/bash",
                    "-lc",
                    "curl -sSf https://sshx.io/get | sh"
                ],
                user="root"
            )

            if install.exit_code != 0:
                raise RuntimeError("SSHX installation failed.")

        container.exec_run(
            [
                "/bin/bash",
                "-lc",
                "pkill -f '[s]shx' 2>/dev/null || true; "
                "rm -f /tmp/sshx.log; "
                "touch /tmp/sshx.log"
            ],
            user="root"
        )

        start_result = container.exec_run(
            [
                "/bin/bash",
                "-lc",
                "SSHX_BIN=$(command -v sshx); "
                "nohup \"$SSHX_BIN\" > /tmp/sshx.log 2>&1 < /dev/null &"
            ],
            user="root"
        )

        if start_result.exit_code != 0:
            raise RuntimeError("Could not start SSHX.")

        link = None

        for _ in range(20):
            await asyncio.sleep(1)

            result = container.exec_run(
                [
                    "/bin/bash",
                    "-lc",
                    "cat /tmp/sshx.log 2>/dev/null"
                ],
                user="root"
            )

            output = result.output.decode(
                "utf-8",
                errors="replace"
            )

            # Remove ANSI terminal escape sequences
            import re
            output = re.sub(
                r"\x1b\[[0-9;?]*[ -/]*[@-~]",
                "",
                output
            )

            # Extract only the real SSHX URL
            match = re.search(
                r"https://sshx\.io/s/[A-Za-z0-9_-]+#[A-Za-z0-9_-]+",
                output
            )

            if match:
                link = match.group(0)
                break

        if not link:
            log_result = container.exec_run(
                [
                    "/bin/bash",
                    "-lc",
                    "tail -30 /tmp/sshx.log 2>/dev/null"
                ],
                user="root"
            )

            log_output = log_result.output.decode(
                "utf-8",
                errors="replace"
            ).strip()

            raise RuntimeError(
                "SSHX link was not generated.\n"
                + (log_output[:500] if log_output else "No SSHX output.")
            )

        embed = discord.Embed(
            title="🔐 VPS SSHX Access",
            description=(
                f"Your **VPS #{vps_id}** SSHX session is ready.\n\n"
                f"🔗 **[Click here to access your VPS]({link})**"
            ),
            color=discord.Color.green()
        )

        embed.add_field(
            name="VPS ID",
            value=f"`#{vps_id}`"
        )

        embed.set_footer(
            text="Keep this SSHX link private."
        )

        try:
            await interaction.user.send(embed=embed)

            await interaction.followup.send(
                f"✅ SSHX link for VPS #{vps_id} has been sent to your DM.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I couldn't DM you. Please enable DMs from this server.",
                ephemeral=True
            )

    except Exception as e:
        await interaction.followup.send(
            f"❌ SSHX error:\n```text\n{str(e)[:900]}\n```",
            ephemeral=True
        )


if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing from .env")

if not PUBLIC_IP or PUBLIC_IP == "YOUR_PUBLIC_IPV4":
    raise SystemExit("Set your real PUBLIC_IP in .env")

if not ADMIN_IDS:
    raise SystemExit("Set your Discord numeric ID in ADMIN_IDS")

bot.run(TOKEN)
