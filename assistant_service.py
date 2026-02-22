"""
Assistant Service - Discord channel monitoring + Gemini prompt generation + Claude Code execution
"""

import os
import asyncio
import discord
from discord.ui import View, Button
import google.generativeai as genai


class ConfirmView(discord.ui.View):
    """User confirmation view for generated prompts"""

    def __init__(self, original_user_id: int):
        super().__init__(timeout=300)  # 5 minutes
        self.confirmed = None
        self.original_user_id = original_user_id

    @discord.ui.button(label="진행", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ 요청자만 확인할 수 있습니다.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.edit_message(content="✅ 진행 중...", view=None)
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ 요청자만 취소할 수 있습니다.", ephemeral=True)
            return
        self.confirmed = False
        await interaction.response.edit_message(content="❌ 취소되었습니다.", view=None)
        self.stop()


class CommitView(discord.ui.View):
    """Commit confirmation view after Claude Code execution"""

    def __init__(self, assistant_service, original_user_id: int):
        super().__init__(timeout=600)  # 10 minutes
        self.assistant_service = assistant_service
        self.original_user_id = original_user_id
        self.committed = None

    @discord.ui.button(label="커밋하기", style=discord.ButtonStyle.primary, emoji="📝")
    async def commit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ 요청자만 커밋할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        # Run git add and commit
        result = await self.assistant_service.run_git_commit()

        if result['success']:
            await interaction.followup.send(f"✅ 커밋 완료!\n```\n{result['message']}\n```", ephemeral=True)
            self.committed = True
        else:
            await interaction.followup.send(f"❌ 커밋 실패:\n```\n{result['error']}\n```", ephemeral=True)
            self.committed = False

        self.stop()

    @discord.ui.button(label="취소 (변경사항 되돌리기)", style=discord.ButtonStyle.danger, emoji="🔄")
    async def revert(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ 요청자만 되돌리기할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        # Run git checkout to revert changes
        result = await self.assistant_service.run_git_revert()

        if result['success']:
            await interaction.followup.send("✅ 변경사항이 되돌려졌습니다.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ 되돌리기 실패:\n```\n{result['error']}\n```", ephemeral=True)

        self.committed = False
        self.stop()


class AssistantService:
    """
    Monitors a Discord channel for development requests,
    uses Gemini to generate prompts, and executes Claude Code.
    """

    def __init__(self, bot):
        self.bot = bot
        self.gemini_model = None
        self.monitor_channel_id = None
        self.working_dir = os.path.dirname(os.path.abspath(__file__))

        # Load channel ID from environment
        channel_id = os.getenv("MONITOR_CHANNEL_ID")
        if channel_id:
            self.monitor_channel_id = int(channel_id)

    async def setup_gemini(self):
        """Initialize Gemini API"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[AssistantService] GEMINI_API_KEY not found - service disabled")
            return False

        try:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel('gemini-2.0-flash')
            print("[AssistantService] Gemini API initialized successfully")
            return True
        except Exception as e:
            print(f"[AssistantService] Failed to initialize Gemini: {e}")
            return False

    async def process_message(self, message: discord.Message):
        """Process a new message from the monitored channel"""
        if not self.gemini_model:
            return

        if not message.content.strip():
            return

        print(f"[AssistantService] Processing message from {message.author}: {message.content[:50]}...")

        # Generate development prompt using Gemini
        prompt = await self.generate_prompt(message.content)

        if not prompt:
            await message.reply("❌ 프롬프트 생성에 실패했습니다.", mention_author=False)
            return

        # Send confirmation to user (ephemeral-like using reply)
        embed = discord.Embed(
            title="🤖 개발 프롬프트 생성됨",
            description=f"다음 프롬프트로 Claude Code를 실행할까요?\n\n```\n{prompt[:1500]}{'...' if len(prompt) > 1500 else ''}\n```",
            color=0x5865F2
        )
        embed.set_footer(text="5분 내에 응답해주세요")

        view = ConfirmView(message.author.id)
        confirm_msg = await message.reply(embed=embed, view=view, mention_author=True)

        # Wait for user confirmation
        await view.wait()

        if view.confirmed is None:
            await confirm_msg.edit(content="⏰ 시간 초과로 취소되었습니다.", embed=None, view=None)
            return

        if not view.confirmed:
            return

        # Execute Claude Code
        await confirm_msg.edit(content="⏳ Claude Code 실행 중... (시간이 걸릴 수 있습니다)", embed=None, view=None)

        result = await self.run_claude_code(prompt)

        # Report results
        await self.report_result(message.channel, message.author.id, result, confirm_msg)

    async def generate_prompt(self, content: str) -> str:
        """Generate a development prompt using Gemini"""
        if not self.gemini_model:
            return None

        system_prompt = """당신은 Discord 봇 개발 프롬프트 생성기입니다.
사용자의 요청을 받아 Claude Code가 실행할 수 있는 구체적인 개발 프롬프트를 생성합니다.

규칙:
1. 프롬프트는 명확하고 구체적이어야 합니다
2. 파일 경로, 함수명, 변수명 등을 구체적으로 명시합니다
3. 구현해야 할 기능의 요구사항을 상세히 작성합니다
4. 기존 코드 구조를 존중하도록 안내합니다
5. 한국어로 설명하되, 코드 관련 용어는 영어를 사용합니다

프로젝트 컨텍스트:
- Discord 봇 프로젝트 (discord.py)
- 주요 파일: piacia.py (메인), api_searcher.py (API), database.py (DB), news_scheduler.py (뉴스)
- PostgreSQL 데이터베이스 사용 (Supabase)
- 슬래시 커맨드 기반

사용자 요청을 분석하여 Claude Code가 바로 실행할 수 있는 개발 프롬프트만 출력하세요.
추가 설명이나 대화 없이 프롬프트만 출력합니다."""

        try:
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                f"{system_prompt}\n\n사용자 요청:\n{content}"
            )
            return response.text.strip()
        except Exception as e:
            print(f"[AssistantService] Gemini error: {e}")
            return None

    async def run_claude_code(self, prompt: str) -> dict:
        """Execute Claude Code CLI with the generated prompt"""
        try:
            # Prepare command with allowed tools for automation
            cmd = [
                "claude",
                "-p", prompt,
                "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(git diff *),Bash(git status *),Bash(python *)"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )

            stdout, stderr = await process.communicate()

            return {
                'success': process.returncode == 0,
                'stdout': stdout.decode('utf-8', errors='replace'),
                'stderr': stderr.decode('utf-8', errors='replace'),
                'returncode': process.returncode
            }
        except FileNotFoundError:
            return {
                'success': False,
                'stdout': '',
                'stderr': 'Claude Code CLI not found. Make sure it is installed and in PATH.',
                'returncode': -1
            }
        except Exception as e:
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1
            }

    async def report_result(self, channel: discord.TextChannel, user_id: int, result: dict, original_msg: discord.Message):
        """Report Claude Code execution results and show commit option"""
        if result['success']:
            # Truncate output if too long
            output = result['stdout']
            if len(output) > 1800:
                output = output[:1800] + "\n... (출력이 잘렸습니다)"

            embed = discord.Embed(
                title="✅ Claude Code 실행 완료",
                description=f"```\n{output}\n```" if output else "실행이 완료되었습니다.",
                color=0x57F287
            )

            # Check if there are changes to commit
            git_status = await self.get_git_status()
            if git_status.get('has_changes'):
                embed.add_field(
                    name="📁 변경된 파일",
                    value=f"```\n{git_status.get('changes', 'N/A')[:500]}\n```",
                    inline=False
                )
                view = CommitView(self, user_id)
                await original_msg.edit(embed=embed, view=view, content=None)
            else:
                embed.add_field(name="📁 변경사항", value="변경된 파일이 없습니다.", inline=False)
                await original_msg.edit(embed=embed, view=None, content=None)
        else:
            error_msg = result['stderr'] or result['stdout'] or "Unknown error"
            if len(error_msg) > 1800:
                error_msg = error_msg[:1800] + "\n... (오류 메시지가 잘렸습니다)"

            embed = discord.Embed(
                title="❌ Claude Code 실행 실패",
                description=f"```\n{error_msg}\n```",
                color=0xED4245
            )
            await original_msg.edit(embed=embed, view=None, content=None)

    async def get_git_status(self) -> dict:
        """Get current git status"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            stdout, _ = await process.communicate()
            changes = stdout.decode('utf-8', errors='replace').strip()

            return {
                'has_changes': bool(changes),
                'changes': changes
            }
        except Exception as e:
            return {'has_changes': False, 'error': str(e)}

    async def run_git_commit(self) -> dict:
        """Run git add and commit with auto-generated message"""
        try:
            # Get diff for commit message
            diff_process = await asyncio.create_subprocess_exec(
                "git", "diff", "--stat",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            diff_stdout, _ = await diff_process.communicate()
            diff_info = diff_stdout.decode('utf-8', errors='replace')[:200]

            # Git add
            add_process = await asyncio.create_subprocess_exec(
                "git", "add", "-A",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            await add_process.communicate()

            # Git commit
            commit_msg = f"feat: Auto-commit by Assistant Service\n\nChanges:\n{diff_info}"
            commit_process = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", commit_msg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            stdout, stderr = await commit_process.communicate()

            if commit_process.returncode == 0:
                return {'success': True, 'message': stdout.decode('utf-8', errors='replace')}
            else:
                return {'success': False, 'error': stderr.decode('utf-8', errors='replace')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def run_git_revert(self) -> dict:
        """Revert uncommitted changes"""
        try:
            # Reset staged changes
            reset_process = await asyncio.create_subprocess_exec(
                "git", "reset", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            await reset_process.communicate()

            # Checkout all changes
            checkout_process = await asyncio.create_subprocess_exec(
                "git", "checkout", ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            stdout, stderr = await checkout_process.communicate()

            if checkout_process.returncode == 0:
                return {'success': True}
            else:
                return {'success': False, 'error': stderr.decode('utf-8', errors='replace')}
        except Exception as e:
            return {'success': False, 'error': str(e)}
