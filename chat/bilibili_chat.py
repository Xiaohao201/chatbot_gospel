# bilibili_video表中增加一个字段：chat_website_url，这个字段的值为https://message.bilibili.com/#/whisper/mid{user_id}，默认字段为null，字段类型为varchar(255)
# 一个数据库表：chat；在关键词搜索，数据存储到数据库之后，也将关键词放入到chat表的字段"source_keyword"中
# 每一条bilibili_video表中的数据，对应生成一条chat表的数据，并存储到chat表的字段"chat_id"中
# 调用AI的API，根据"source_keyword"里的内容生成对应的开场白，并存储到chat表的字段"chat_start"中
# 打开bilibili_video表中的chat_website_url字段，一个一个打开，使用"chat_start"的内容，填入到：
#<div class="_MessageSendBox__Textarea_1izxa_42 msb-textarea" style="--brt-editor-padding-hrz: 16px;"><div class="brt-root"><div class="brt-placeholder">请输入消息内容</div><div class="brt-editor" contenteditable="true"></div></div></div>
# 然后，点击：<div class="_MessageSendBox__SendBtn_1izxa_69 _IsDisabled_1izxa_22">发送</div>按钮
# 每点击一次发送按钮，就记录一次时间，并存储到chat表的字段"chat_timestamp"中

# -*- coding: utf-8 -*-
# @Author  : Chat Automation System
# @Time    : 2024/12/26
# @Desc    : B站私信自动化系统
from dotenv import load_dotenv
load_dotenv()  
import asyncio
import json
import time
import os
import sys
from typing import Dict, List, Optional, Union

from playwright.async_api import async_playwright, BrowserContext, Page

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from tools import utils
    from config import base_config
    from config.call_qwen import call_qwen
    from config.call_bigmodel import call_bigmodel
    from database.db_session import get_session
    from database.models import BilibiliVideo, BilibiliChat
    from sqlalchemy import select, update, and_, or_
    from sqlalchemy.orm import selectinload
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保从项目根目录运行此脚本: python chat/bilibili_chat.py")
    sys.exit(1)


class BilibiliChatAutomation:
    """
    B站私信自动化系统
    实现自动生成开场白并发送私信的功能
    """

    def __init__(self):
        self.browser_context: Optional[BrowserContext] = None
        self.playwright = None

    async def create_chat_table(self):
        """创建chat表 - SQLAlchemy会自动创建"""
        # 表结构由SQLAlchemy ORM自动管理
        utils.logger.info("[BilibiliChatAutomation] chat表创建完成 (SQLAlchemy自动管理)")

    async def add_chat_website_url_column(self):
        """在bilibili_video表中增加chat_website_url字段 - SQLAlchemy模型已定义"""
        # chat_website_url字段已在BilibiliVideo模型中定义
        utils.logger.info("[BilibiliChatAutomation] chat_website_url字段检查完成 (SQLAlchemy模型已定义)")

    async def update_chat_website_urls(self):
        """更新bilibili_video表中的chat_website_url字段"""
        async with get_session() as session:
            # 查询所有没有chat_website_url的记录
            stmt = select(BilibiliVideo).where(
                or_(BilibiliVideo.chat_website_url.is_(None), BilibiliVideo.chat_website_url == '')
            )
            result = await session.execute(stmt)
            videos = result.scalars().all()

            updated_count = 0
            for video in videos:
                if video.user_id:
                    video.chat_website_url = f"https://message.bilibili.com/#/whisper/mid{video.user_id}"
                    video.last_modify_ts = utils.get_current_time()
                    updated_count += 1

            await session.commit()
            utils.logger.info(f"[BilibiliChatAutomation] 更新了 {updated_count} 条记录的chat_website_url")

    async def create_chat_records_from_videos(self):
        """为bilibili_video表中的数据创建对应的chat表记录"""
        async with get_session() as session:
            # 查询所有有source_keyword但在chat表中没有对应记录的视频
            subquery = select(BilibiliChat.chat_id)
            stmt = select(BilibiliVideo).where(
                and_(
                    BilibiliVideo.source_keyword.isnot(None),
                    BilibiliVideo.source_keyword != '',
                    ~BilibiliVideo.video_id.in_(subquery)
                )
            )
            result = await session.execute(stmt)
            videos = result.scalars().all()

            created_count = 0
            for video in videos:
                chat_record = BilibiliChat(
                    chat_id=str(video.video_id),
                    source_keyword=video.source_keyword,
                    status="pending",
                    add_ts=utils.get_current_time(),
                    last_modify_ts=utils.get_current_time()
                )
                session.add(chat_record)
                created_count += 1

            await session.commit()
            utils.logger.info(f"[BilibiliChatAutomation] 创建了 {created_count} 条chat记录")

    async def generate_chat_start_messages(self):
        """调用AI API生成开场白"""
        async with get_session() as session:
            # 查询所有还没有chat_start的记录，并关联BilibiliVideo表获取更多信息
            stmt = select(BilibiliChat, BilibiliVideo).join(
                BilibiliVideo, BilibiliChat.chat_id == BilibiliVideo.video_id
            ).where(
                and_(
                    or_(BilibiliChat.chat_start.is_(None), BilibiliChat.chat_start == ''),
                    BilibiliChat.source_keyword.isnot(None),
                    BilibiliChat.source_keyword != ''
                )
            ).limit(10)
            result = await session.execute(stmt)
            chat_video_pairs = result.all()

            for chat_record, video in chat_video_pairs:
                try:
                    # 构建包含对象内容的prompt
                    content_info = []
                    
                    # 添加关键词
                    content_info.append(f"搜索关键词：{chat_record.source_keyword}")
                    
                    # 添加UP主昵称
                    if video.nickname:
                        content_info.append(f"UP主昵称：{video.nickname}")
                    
                    # 添加视频标题
                    if video.title:
                        content_info.append(f"视频标题：{video.title}")
                    
                    # 添加视频描述（截取前200字，避免过长）
                    if video.desc:
                        desc_summary = video.desc[:200] + "..." if len(video.desc) > 200 else video.desc
                        content_info.append(f"视频描述：{desc_summary}")
                    
                    # 添加视频类型
                    if video.video_type:
                        content_info.append(f"视频类型：{video.video_type}")
                    
                    # 添加互动数据
                    engagement_info = []
                    if video.liked_count:
                        engagement_info.append(f"{video.liked_count}赞")
                    if video.video_comment:
                        engagement_info.append(f"{video.video_comment}评论")
                    if video.video_play_count:
                        engagement_info.append(f"{video.video_play_count}播放")
                    if engagement_info:
                        content_info.append(f"互动情况：{', '.join(engagement_info)}")
                    
                    # 构建完整的prompt
                    content_str = "\n".join(content_info)
                    prompt = f"根据以下信息，生成一段友好的B站私信开场白：\n\n{content_str}"

                    # chat_start = await self.call_qwen_api(prompt)
                    chat_start = await self.call_bigmodel_api(prompt)

                    if chat_start:
                        chat_record.chat_start = chat_start
                        chat_record.last_modify_ts = utils.get_current_time()
                        utils.logger.info(f"[BilibiliChatAutomation] 为chat_id {chat_record.chat_id} (UP主:{video.nickname}) 生成开场白: {chat_start}")
                        await asyncio.sleep(1)  # 避免API调用过于频繁

                except Exception as e:
                    utils.logger.error(f"[BilibiliChatAutomation] 生成开场白失败 chat_id={chat_record.chat_id}: {e}")

            await session.commit()


    async def call_bigmodel_api(self, prompt: str) -> Optional[str]:
        """调用智谱AI API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的B站私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 结合对方的内容特点，个性化定制 6. 字数控制在60字以内"}
            ]
            import concurrent.futures
            import asyncio
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, call_bigmodel, messages)
            if result and result.choices:
                return result.choices[0].message.content.strip()
            else:
                utils.logger.error(f"[BilibiliChatAutomation] 智谱AI API调用失败: {result}")
                return None
        except Exception as e:
            utils.logger.error(f"[BilibiliChatAutomation] 智谱AI API调用异常: {e}")
            return None

    async def call_qwen_api(self, prompt: str) -> Optional[str]:
        """调用通义千问API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的B站私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 字数控制在50字以内"}
            ]

            # 在线程池中运行同步API调用
            import concurrent.futures
            import asyncio

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, call_qwen, messages)

            if result and "choices" in result:
                return result["choices"][0]["message"]["content"].strip()
            else:
                utils.logger.error(f"[BilibiliChatAutomation] 通义千问API调用失败: {result}")
                return None

        except Exception as e:
            utils.logger.error(f"[BilibiliChatAutomation] 通义千问API调用异常: {e}")
            return None

    async def check_login_status(self, page: Page) -> bool:
        """检测当前页面是否已登录"""
        try:
            # 方法1: 检查是否有登录按钮（未登录时会有登录按钮）
            login_selectors = [
                "a:has-text('登录')",
                "button:has-text('登录')",
                "[data-e2e='login-button']",
                ".login-btn"
            ]

            for selector in login_selectors:
                try:
                    login_button = page.locator(selector).first
                    if await login_button.count() > 0 and await login_button.is_visible():
                        utils.logger.warning(f"[BilibiliChatAutomation] 检测到未登录状态（发现登录按钮: {selector}）")
                        return False
                except:
                    continue

            # 方法2: 检查用户头像或用户信息元素（已登录时会有）
            user_selectors = [
                ".avatar",
                "[data-testid='user-avatar']",
                ".user-avatar",
                "[class*='avatar']"
            ]

            for selector in user_selectors:
                try:
                    user_element = page.locator(selector).first
                    if await user_element.count() > 0 and await user_element.is_visible():
                        utils.logger.info(f"[BilibiliChatAutomation] 检测到已登录状态（发现用户元素: {selector}）")
                        return True
                except:
                    continue

            # 方法3: 检查URL是否包含登录相关参数
            current_url = page.url
            if 'login' in current_url.lower() or 'passport' in current_url:
                utils.logger.warning(f"[BilibiliChatAutomation] 检测到未登录状态（URL包含登录信息: {current_url}）")
                return False

            # 方法4: 检查页面标题
            page_title = await page.title()
            if '登录' in page_title or 'Login' in page_title:
                utils.logger.warning(f"[BilibiliChatAutomation] 检测到未登录状态（页面标题: {page_title}）")
                return False

            # 如果以上方法都无法确定，默认认为可能未登录，但继续尝试
            utils.logger.warning("[BilibiliChatAutomation] 无法确定登录状态，将尝试发送私信")
            return True

        except Exception as e:
            utils.logger.warning(f"[BilibiliChatAutomation] 检测登录状态时出错: {e}，将尝试发送私信")
            return True

    async def send_chat_messages(self):
        """使用Playwright自动化发送私信 - 循环处理所有符合条件的记录"""
        # 初始化Playwright浏览器
        await self.init_browser()

        try:
            while True:
                async with get_session() as session:
                    # 查询待发送的私信，每次处理1条
                    stmt = select(BilibiliChat, BilibiliVideo).join(
                        BilibiliVideo, BilibiliChat.chat_id == BilibiliVideo.video_id
                    ).where(
                        and_(
                            BilibiliChat.status == 'pending',
                            BilibiliChat.chat_start.isnot(None),
                            BilibiliChat.chat_start != '',
                            BilibiliVideo.chat_website_url.isnot(None),
                            BilibiliVideo.chat_website_url != ''
                        )
                    ).limit(1)
                    result = await session.execute(stmt)
                    chat_video_pairs = result.all()

                    if not chat_video_pairs:
                        utils.logger.info("[BilibiliChatAutomation] 所有符合条件的私信都已处理完成")
                        break

                    chat_record, video = chat_video_pairs[0]
                    chat_id = chat_record.chat_id
                    chat_start = chat_record.chat_start
                    chat_url = video.chat_website_url

                    page = None
                    try:
                        utils.logger.info(f"[BilibiliChatAutomation] 开始处理私信 chat_id={chat_id}")

                        # 打开私信页面
                        page = await self.browser_context.new_page()
                        await page.goto(chat_url)
                        await page.wait_for_load_state('networkidle')
                        await asyncio.sleep(3)  # 等待页面加载

                        # 检测登录状态
                        is_logged_in = await self.check_login_status(page)
                        if not is_logged_in:
                            utils.logger.warning("[BilibiliChatAutomation] 检测到未登录状态")
                            utils.logger.info("=" * 80)
                            utils.logger.info("【重要提示】当前账号未登录，无法发送私信")
                            utils.logger.info("请按照以下步骤操作：")
                            utils.logger.info("1. 在打开的浏览器中手动登录B站账号")
                            utils.logger.info("2. 登录成功后，本程序将自动继续执行")
                            utils.logger.info("=" * 80)

                            # 等待用户登录，每5秒检测一次登录状态
                            max_wait_time = 600  # 最多等待10分钟
                            wait_time = 0
                            check_interval = 5  # 每5秒检测一次

                            utils.logger.info("[BilibiliChatAutomation] 正在等待用户登录...")
                            while wait_time < max_wait_time:
                                await asyncio.sleep(check_interval)
                                wait_time += check_interval

                                # 重新检测登录状态
                                is_logged_in = await self.check_login_status(page)
                                if is_logged_in:
                                    utils.logger.info("[BilibiliChatAutomation] 检测到登录成功！继续执行...")
                                    break

                                # 每分钟提示一次
                                if wait_time % 60 == 0:
                                    utils.logger.info(f"[BilibiliChatAutomation] 已等待 {wait_time//60} 分钟，请尽快登录...")

                            if not is_logged_in:
                                raise Exception(f"等待登录超时（已等待 {max_wait_time//60} 分钟），程序终止。请重新运行程序并确保登录状态。")

                        # 等待输入框加载
                        await page.wait_for_selector("div.brt-editor", timeout=10000)

                        # 找到输入框并输入消息
                        editor = page.locator("div.brt-editor")
                        await editor.click()

                        # 清空现有内容并输入新内容
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Delete")
                        await page.keyboard.type(chat_start)
                        await asyncio.sleep(1)

                        # 找到发送按钮并点击（未禁用的按钮）
                        send_button = page.locator("div._MessageSendBox__SendBtn_1izxa_69:not(._IsDisabled_1izxa_22)")
                        await send_button.click()

                        # 记录发送时间并更新状态
                        send_timestamp = utils.get_current_time()
                        chat_record.status = 'sent'
                        chat_record.chat_timestamp = send_timestamp
                        chat_record.last_modify_ts = send_timestamp

                        utils.logger.info(f"[BilibiliChatAutomation] 成功发送私信 chat_id={chat_id}")

                        await page.close()
                        await asyncio.sleep(5)  # 发送间隔，避免被限制

                    except Exception as e:
                        utils.logger.error(f"[BilibiliChatAutomation] 发送私信失败 chat_id={chat_id}: {e}")

                        # 更新状态为失败
                        current_ts = utils.get_current_time()
                        chat_record.status = 'failed'
                        chat_record.last_modify_ts = current_ts

                        # 确保页面被正确关闭
                        if page:
                            try:
                                await page.close()
                            except:
                                pass

                        # 发送失败也继续处理下一条
                        await asyncio.sleep(2)

                    await session.commit()

        finally:
            await self.close_browser()

    async def init_browser(self):
        """初始化Playwright浏览器"""
        self.playwright = await async_playwright().start()

        # 使用现有的浏览器用户数据目录（如果有登录状态）
        user_data_dir = None
        if hasattr(base_config, 'USER_DATA_DIR') and base_config.USER_DATA_DIR:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", base_config.USER_DATA_DIR.replace('%s', 'bili'))
            if not os.path.exists(user_data_dir):
                user_data_dir = None

        if user_data_dir and os.path.exists(user_data_dir):
            # 使用持久化上下文
            self.browser_context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=base_config.HEADLESS,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        else:
            # 创建新的浏览器上下文
            browser = await self.playwright.chromium.launch(
                headless=base_config.HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            self.browser_context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        # 添加反检测脚本
        await self.browser_context.add_init_script(path="libs/stealth.min.js")
        utils.logger.info("[BilibiliChatAutomation] Playwright浏览器初始化完成")

    async def close_browser(self):
        """关闭浏览器"""
        try:
            if self.browser_context:
                await self.browser_context.close()
                self.browser_context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            utils.logger.info("[BilibiliChatAutomation] 浏览器已关闭")
        except Exception as e:
            utils.logger.error(f"[BilibiliChatAutomation] 关闭浏览器时出错: {e}")

    async def run_full_automation(self):
        """运行完整的自动化流程"""
        try:
            # 1. 创建必要的表结构
            await self.create_chat_table()
            await self.add_chat_website_url_column()

            # 2. 更新数据
            await self.update_chat_website_urls()
            await self.create_chat_records_from_videos()

            # 3. 生成开场白
            await self.generate_chat_start_messages()

            # 4. 发送私信
            await self.send_chat_messages()

            utils.logger.info("[BilibiliChatAutomation] 自动化流程完成")

        except Exception as e:
            utils.logger.error(f"[BilibiliChatAutomation] 自动化流程执行失败: {e}")
            raise


async def main():
    """主函数"""
    # 初始化数据库连接
    from database import db
    await db.init_db()

    chat_automation = BilibiliChatAutomation()
    await chat_automation.run_full_automation()


if __name__ == "__main__":
    asyncio.run(main())