# 抖音私信自动化系统
# 在douyin_aweme表中增加一个字段：chat_website_url，这个字段的值为https://www.douyin.com/user/{user_id}，默认字段为null，字段类型为varchar(255)
# 一个数据库表：douyin_chat；在关键词搜索，数据存储到数据库之后，也将关键词放入到douyin_chat表的字段"source_keyword"中
# 每一条douyin_aweme表中的数据，对应生成一条douyin_chat表的数据，并存储到douyin_chat表的字段"chat_id"中
# 调用AI的API，根据"source_keyword"里的内容生成对应的开场白，并存储到douyin_chat表的字段"chat_start"中
# 打开douyin_aweme表中的chat_website_url字段，一个一个打开，使用"chat_start"的内容，填入到私信输入框中
# 然后，点击发送按钮
# 每点击一次发送按钮，就记录一次时间，并存储到douyin_chat表的字段"chat_timestamp"中

# -*- coding: utf-8 -*-
# @Author  : Chat Automation System
# @Time    : 2024/12/26
# @Desc    : 抖音私信自动化系统
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
    from database.models import DouyinAweme, DouyinChat
    from sqlalchemy import select, update, and_, or_
    from sqlalchemy.orm import selectinload
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保从项目根目录运行此脚本: python chat/douyin_chat.py")
    sys.exit(1)


class DouyinChatAutomation:
    """
    抖音私信自动化系统
    实现自动生成开场白并发送私信的功能
    """

    def __init__(self):
        self.browser_context: Optional[BrowserContext] = None
        self.playwright = None

    async def create_chat_table(self):
        """创建douyin_chat表 - SQLAlchemy会自动创建"""
        # 表结构由SQLAlchemy ORM自动管理
        utils.logger.info("[DouyinChatAutomation] douyin_chat表创建完成 (SQLAlchemy自动管理)")

    async def add_chat_website_url_column(self):
        """在douyin_aweme表中增加chat_website_url字段 - SQLAlchemy模型已定义"""
        # chat_website_url字段已在DouyinAweme模型中定义
        utils.logger.info("[DouyinChatAutomation] chat_website_url字段检查完成 (SQLAlchemy模型已定义)")

    async def update_chat_website_urls(self):
        """更新douyin_aweme表中的chat_website_url字段"""
        async with get_session() as session:
            # 查询所有没有chat_website_url的记录
            stmt = select(DouyinAweme).where(
                or_(DouyinAweme.chat_website_url.is_(None), DouyinAweme.chat_website_url == '')
            )
            result = await session.execute(stmt)
            awemes = result.scalars().all()

            updated_count = 0
            for aweme in awemes:
                if aweme.sec_uid:
                    aweme.chat_website_url = f"https://www.douyin.com/user/{aweme.sec_uid}"
                    aweme.last_modify_ts = utils.get_current_time()
                    updated_count += 1

            await session.commit()
            utils.logger.info(f"[DouyinChatAutomation] 更新了 {updated_count} 条记录的chat_website_url")

    async def create_chat_records_from_awemes(self):
        """为douyin_aweme表中的数据创建对应的douyin_chat表记录"""
        async with get_session() as session:
            # 查询所有有source_keyword但在douyin_chat表中没有对应记录的视频
            subquery = select(DouyinChat.chat_id)
            stmt = select(DouyinAweme).where(
                and_(
                    DouyinAweme.source_keyword.isnot(None),
                    DouyinAweme.source_keyword != '',
                    ~DouyinAweme.aweme_id.in_(subquery)
                )
            )
            result = await session.execute(stmt)
            awemes = result.scalars().all()

            created_count = 0
            for aweme in awemes:
                chat_record = DouyinChat(
                    chat_id=aweme.aweme_id,
                    source_keyword=aweme.source_keyword,
                    status="pending",
                    add_ts=utils.get_current_time(),
                    last_modify_ts=utils.get_current_time()
                )
                session.add(chat_record)
                created_count += 1

            await session.commit()
            utils.logger.info(f"[DouyinChatAutomation] 创建了 {created_count} 条douyin_chat记录")

    async def generate_chat_start_messages(self):
        """调用AI API生成开场白"""
        async with get_session() as session:
            # 查询所有还没有chat_start的记录，并关联DouyinAweme表获取更多信息
            stmt = select(DouyinChat, DouyinAweme).join(
                DouyinAweme, DouyinChat.chat_id == DouyinAweme.aweme_id
            ).where(
                and_(
                    or_(DouyinChat.chat_start.is_(None), DouyinChat.chat_start == ''),
                    DouyinChat.source_keyword.isnot(None),
                    DouyinChat.source_keyword != ''
                )
            ).limit(10)
            result = await session.execute(stmt)
            chat_aweme_pairs = result.all()

            for chat_record, aweme in chat_aweme_pairs:
                try:
                    # 构建包含对象内容的prompt
                    content_info = []
                    
                    # 添加关键词
                    content_info.append(f"搜索关键词：{chat_record.source_keyword}")
                    
                    # 添加创作者昵称
                    if aweme.nickname:
                        content_info.append(f"创作者昵称：{aweme.nickname}")
                    
                    # 添加视频标题
                    if aweme.title:
                        content_info.append(f"视频标题：{aweme.title}")
                    
                    # 添加视频描述（截取前200字，避免过长）
                    if aweme.desc:
                        desc_summary = aweme.desc[:200] + "..." if len(aweme.desc) > 200 else aweme.desc
                        content_info.append(f"视频描述：{desc_summary}")
                    
                    # 添加用户签名
                    if aweme.user_signature:
                        content_info.append(f"用户签名：{aweme.user_signature}")
                    
                    # 添加视频类型
                    if aweme.aweme_type:
                        content_info.append(f"视频类型：{aweme.aweme_type}")
                    
                    # 添加IP归属地
                    if aweme.ip_location:
                        content_info.append(f"IP归属地：{aweme.ip_location}")
                    
                    # 添加互动数据
                    engagement_info = []
                    if aweme.liked_count:
                        engagement_info.append(f"{aweme.liked_count}赞")
                    if aweme.comment_count:
                        engagement_info.append(f"{aweme.comment_count}评论")
                    if aweme.share_count:
                        engagement_info.append(f"{aweme.share_count}分享")
                    if aweme.collected_count:
                        engagement_info.append(f"{aweme.collected_count}收藏")
                    if engagement_info:
                        content_info.append(f"互动情况：{', '.join(engagement_info)}")
                    
                    # 构建完整的prompt
                    content_str = "\n".join(content_info)
                    prompt = f"根据以下信息，生成一段友好的抖音私信开场白：\n\n{content_str}"

                    # chat_start = await self.call_qwen_api(prompt)
                    chat_start = await self.call_bigmodel_api(prompt)

                    if chat_start:
                        chat_record.chat_start = chat_start
                        chat_record.last_modify_ts = utils.get_current_time()
                        utils.logger.info(f"[DouyinChatAutomation] 为chat_id {chat_record.chat_id} (创作者:{aweme.nickname}) 生成开场白: {chat_start}")
                        await asyncio.sleep(1)  # 避免API调用过于频繁

                except Exception as e:
                    utils.logger.error(f"[DouyinChatAutomation] 生成开场白失败 chat_id={chat_record.chat_id}: {e}")

            await session.commit()


    async def call_bigmodel_api(self, prompt: str) -> Optional[str]:
        """调用智谱AI API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的抖音私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 结合对方的内容特点，个性化定制 6. 字数控制在60字以内"}
            ]
            import concurrent.futures
            import asyncio
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, call_bigmodel, messages)
            if result and result.choices:
                return result.choices[0].message.content.strip()
            else:
                utils.logger.error(f"[DouyinChatAutomation] 智谱AI API调用失败: {result}")
                return None  

        except Exception as e:
            utils.logger.error(f"[DouyinChatAutomation] 智谱AI API调用异常: {e}")
            return None



    async def call_qwen_api(self, prompt: str) -> Optional[str]:
        """调用通义千问API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的抖音私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 字数控制在50字以内"}
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
                utils.logger.error(f"[DouyinChatAutomation] 通义千问API调用失败: {result}")
                return None

        except Exception as e:
            utils.logger.error(f"[DouyinChatAutomation] 通义千问API调用异常: {e}")
            return None

    async def send_chat_messages(self):
        """使用Playwright自动化发送私信 - 循环处理所有符合条件的记录"""
        # 初始化Playwright浏览器
        await self.init_browser()

        try:
            while True:
                async with get_session() as session:
                    # 查询待发送的私信，每次处理1条
                    stmt = select(DouyinChat, DouyinAweme).join(
                        DouyinAweme, DouyinChat.chat_id == DouyinAweme.aweme_id
                    ).where(
                        and_(
                            DouyinChat.status == 'pending',
                            DouyinChat.chat_start.isnot(None),
                            DouyinChat.chat_start != '',
                            DouyinAweme.chat_website_url.isnot(None),
                            DouyinAweme.chat_website_url != ''
                        )
                    ).limit(1)
                    result = await session.execute(stmt)
                    chat_aweme_pairs = result.all()

                    if not chat_aweme_pairs:
                        utils.logger.info("[DouyinChatAutomation] 所有符合条件的私信都已处理完成")
                        break

                    chat_record, aweme = chat_aweme_pairs[0]
                    chat_id = chat_record.chat_id
                    chat_start = chat_record.chat_start
                    chat_url = aweme.chat_website_url

                    page = None
                    try:
                        utils.logger.info(f"[DouyinChatAutomation] 开始处理私信 chat_id={chat_id}")

                        # 打开用户主页
                        page = await self.browser_context.new_page()
                        await page.goto(chat_url, timeout=30000)  # 30秒超时

                        # 使用多种策略确保页面加载完成
                        try:
                            # 首先等待DOM内容加载
                            await page.wait_for_load_state('domcontentloaded', timeout=10000)
                        except Exception:
                            try:
                                # 如果超时，使用更短的等待
                                await page.wait_for_load_state('load', timeout=5000)
                            except Exception:
                                # 如果还是超时，至少等待页面基本加载
                                pass

                        # 等待抖音页面的关键元素出现，或者使用时间等待
                        try:
                            # 尝试等待用户头像或用户名等关键元素
                            await page.wait_for_selector('.avatar, [data-testid="user-avatar"], .user-info', timeout=5000)
                        except:
                            # 如果关键元素没找到，等待一段时间
                            await asyncio.sleep(2)

                        # 最终确保页面至少有基本内容
                        await page.wait_for_function(
                            '() => document.readyState === "complete" || document.body.innerHTML.length > 1000',
                            timeout=5000
                        )

                        # 检测登录状态
                        is_logged_in = await self.check_login_status(page)
                        if not is_logged_in:
                            utils.logger.warning("[DouyinChatAutomation] 检测到未登录状态")
                            utils.logger.info("=" * 80)
                            utils.logger.info("【重要提示】当前账号未登录，无法发送私信")
                            utils.logger.info("请按照以下步骤操作：")
                            utils.logger.info("1. 在打开的浏览器中手动登录抖音账号")
                            utils.logger.info("2. 登录成功后，本程序将自动继续执行")
                            utils.logger.info("=" * 80)

                            # 等待用户登录，每5秒检测一次登录状态
                            max_wait_time = 600  # 最多等待10分钟
                            wait_time = 0
                            check_interval = 5  # 每5秒检测一次

                            utils.logger.info("[DouyinChatAutomation] 正在等待用户登录...")
                            while wait_time < max_wait_time:
                                await asyncio.sleep(check_interval)
                                wait_time += check_interval

                                # 重新检测登录状态
                                is_logged_in = await self.check_login_status(page)
                                if is_logged_in:
                                    utils.logger.info("[DouyinChatAutomation] 检测到登录成功！继续执行...")
                                    break

                                # 每分钟提示一次
                                if wait_time % 60 == 0:
                                    utils.logger.info(f"[DouyinChatAutomation] 已等待 {wait_time//60} 分钟，请尽快登录...")

                            if not is_logged_in:
                                raise Exception(f"等待登录超时（已等待 {max_wait_time//60} 分钟），程序终止。请重新运行程序并确保登录状态。")

                        # 尝试找到私信按钮并点击
                        # 根据实际HTML元素优化选择器
                        private_message_selectors = [
                            # 策略1: 直接定位私信按钮（最精确）
                            "button.semi-button.semi-button-secondary:has-text('私信')",

                            # 策略2: 通过span文本定位（匹配实际HTML结构）
                            "button.semi-button-secondary span.semi-button-content:has-text('私信')",

                            # 策略3: 通用的文本匹配
                            "button:has-text('私信')",

                            # 策略4: 通过data-e2e属性
                            "button[data-e2e='user-info-follow-btn'] + button",

                            # 策略5: 类名模式匹配（处理动态类名）
                            "button[class*='semi-button-secondary']"
                        ]

                        message_button = None
                        successful_selector = None

                        for selector in private_message_selectors:
                            try:
                                message_button = page.locator(selector).first
                                # 等待元素出现并检查可见性
                                if await message_button.count() > 0:
                                    # 等待元素变为可见状态
                                    try:
                                        await message_button.wait_for(state='visible', timeout=3000)
                                        if await message_button.is_visible():
                                            successful_selector = selector
                                            utils.logger.info(f"[DouyinChatAutomation] 找到私信按钮: {selector}")
                                            break
                                    except Exception:
                                        continue
                            except Exception:
                                continue

                        if message_button and successful_selector:
                            try:
                                # 滚动到按钮可见区域
                                await message_button.scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)

                                # 检查按钮是否被禁用（可能未登录）
                                is_disabled = await message_button.is_disabled()
                                if is_disabled:
                                    raise Exception("私信按钮处于禁用状态，可能是因为未登录或已被关注")

                                # 点击按钮
                                await message_button.click(timeout=5000)
                                await asyncio.sleep(2)  # 等待私信弹窗加载
                                utils.logger.info(f"[DouyinChatAutomation] 成功点击私信按钮")
                            except Exception as click_error:
                                raise Exception(f"点击私信按钮失败: {click_error}")

                            # 找到输入框并输入消息
                            # 根据实际HTML元素优化选择器
                            input_selectors = [
                                # 策略1: 精确匹配Draft.js编辑器的contenteditable div
                                "[data-e2e='msg-input'] [contenteditable='true']",

                                # 策略2: 通过placeholder定位
                                "[contenteditable='true'][aria-describedby*='placeholder']",

                                # 策略3: 通过类名定位DraftEditor编辑器
                                ".public-DraftEditor-content[contenteditable='true']",

                                # 策略4: 通用contenteditable
                                "[contenteditable='true']",

                                # 策略5: 通过data-e2e属性
                                "[data-e2e='msg-input']"
                            ]

                            input_element = None
                            for selector in input_selectors:
                                try:
                                    input_element = page.locator(selector).first
                                    if await input_element.is_visible():
                                        utils.logger.info(f"[DouyinChatAutomation] 找到输入框: {selector}")
                                        break
                                except:
                                    continue

                            if input_element:
                                await input_element.fill(chat_start)
                                await asyncio.sleep(1)

                                # 找到发送按钮并点击
                                # 根据实际HTML元素优化选择器（注意发送按钮是span不是button）
                                send_selectors = [
                                    # 策略1: 精确匹配发送按钮的span（实际HTML结构）
                                    "span.e2e-send-msg-btn",

                                    # 策略2: 通过父容器定位发送按钮
                                    "[data-e2e='msg-input'] .bLjRcrJd span.e2e-send-msg-btn",

                                    # 策略3: 通过SVG图标定位
                                    "span.e2e-send-msg-btn svg",

                                    # 策略4: 通用的文本匹配（可能不准确）
                                    "button:has-text('发送')",
                                    "button:has-text('发消息')",

                                    # 策略5: 通过类名
                                    ".e2e-send-msg-btn"
                                ]

                                send_button = None
                                for selector in send_selectors:
                                    try:
                                        send_button = page.locator(selector).first
                                        if await send_button.is_visible():
                                            utils.logger.info(f"[DouyinChatAutomation] 找到发送按钮: {selector}")
                                            break
                                    except:
                                        continue

                                if send_button:
                                    await send_button.click()

                                    # 记录发送时间并更新状态
                                    send_timestamp = utils.get_current_time()
                                    chat_record.status = 'sent'
                                    chat_record.chat_timestamp = send_timestamp
                                    chat_record.last_modify_ts = send_timestamp

                                    utils.logger.info(f"[DouyinChatAutomation] 成功发送私信 chat_id={chat_id}")

                                    # 等待2秒
                                    await asyncio.sleep(2)
                                else:
                                    raise Exception("未找到发送按钮")
                            else:
                                raise Exception("未找到输入框")
                        else:
                            raise Exception("未找到私信按钮")

                        await page.close()
                        await asyncio.sleep(5)  # 发送间隔，避免被限制

                    except Exception as e:
                        utils.logger.error(f"[DouyinChatAutomation] 发送私信失败 chat_id={chat_id}: {e}")

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
                        utils.logger.warning(f"[DouyinChatAutomation] 检测到未登录状态（发现登录按钮: {selector}）")
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
                        utils.logger.info(f"[DouyinChatAutomation] 检测到已登录状态（发现用户元素: {selector}）")
                        return True
                except:
                    continue

            # 方法3: 检查URL是否包含登录相关参数
            current_url = page.url
            if 'login' in current_url.lower() or 'passport' in current_url:
                utils.logger.warning(f"[DouyinChatAutomation] 检测到未登录状态（URL包含登录信息: {current_url}）")
                return False

            # 方法4: 检查页面标题
            page_title = await page.title()
            if '登录' in page_title or 'Login' in page_title:
                utils.logger.warning(f"[DouyinChatAutomation] 检测到未登录状态（页面标题: {page_title}）")
                return False

            # 如果以上方法都无法确定，默认认为可能未登录，但继续尝试
            utils.logger.warning("[DouyinChatAutomation] 无法确定登录状态，将尝试发送私信")
            return True

        except Exception as e:
            utils.logger.warning(f"[DouyinChatAutomation] 检测登录状态时出错: {e}，将尝试发送私信")
            return True

    async def init_browser(self):
        """初始化Playwright浏览器 - 使用Chrome，与七大平台保持浏览器类型一致"""
        self.playwright = await async_playwright().start()
        chromium = self.playwright.chromium

        # 使用现有的浏览器用户数据目录（如果有登录状态）
        user_data_dir = None
        if hasattr(base_config, 'USER_DATA_DIR') and base_config.USER_DATA_DIR:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", base_config.USER_DATA_DIR.replace('%s', 'dy'))
            if not os.path.exists(user_data_dir):
                user_data_dir = None

        if user_data_dir and os.path.exists(user_data_dir):
            # 使用持久化上下文，保持登录状态
            self.browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=base_config.HEADLESS,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        else:
            # 创建新的浏览器上下文
            browser = await chromium.launch(
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
        utils.logger.info("[DouyinChatAutomation] Playwright浏览器初始化完成")

    async def close_browser(self):
        """关闭Playwright浏览器"""
        try:
            if self.browser_context:
                await self.browser_context.close()
                self.browser_context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            utils.logger.info("[DouyinChatAutomation] Playwright浏览器已关闭")
        except Exception as e:
            utils.logger.error(f"[DouyinChatAutomation] 关闭浏览器时出错: {e}")

    async def run_full_automation(self):
        """运行完整的自动化流程"""
        try:
            # 1. 创建必要的表结构
            await self.create_chat_table()
            await self.add_chat_website_url_column()

            # 2. 更新数据
            await self.update_chat_website_urls()
            await self.create_chat_records_from_awemes()

            # 3. 生成开场白
            await self.generate_chat_start_messages()

            # 4. 发送私信
            await self.send_chat_messages()

            utils.logger.info("[DouyinChatAutomation] 自动化流程完成")

        except Exception as e:
            utils.logger.error(f"[DouyinChatAutomation] 自动化流程执行失败: {e}")
            raise


async def main():
    """主函数"""
    # 初始化数据库连接
    from database import db
    await db.init_db()

    chat_automation = DouyinChatAutomation()
    await chat_automation.run_full_automation()


if __name__ == "__main__":
    asyncio.run(main())
