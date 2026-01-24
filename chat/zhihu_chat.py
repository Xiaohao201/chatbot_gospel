# zhihu_content表中增加一个字段：chat_website_url，这个字段的值为https://www.zhihu.com/people/{user_url_token}，默认字段为null，字段类型为varchar(255)
# 一个数据库表：zhihu_chat；在关键词搜索，数据存储到数据库之后，也将关键词放入到zhihu_chat表的字段"source_keyword"中
# 每一条zhihu_content表中的数据，对应生成一条zhihu_chat表的数据，并存储到zhihu_chat表的字段"chat_id"中
# 调用AI的API，根据"source_keyword"里的内容生成对应的开场白，并存储到zhihu_chat表的字段"chat_start"中
# 打开zhihu_content表中的chat_website_url字段，一个一个打开，使用"chat_start"的内容，填入到私信输入框中
# 然后，点击发送按钮
# 每点击一次发送按钮，就记录一次时间，并存储到zhihu_chat表的字段"chat_timestamp"中

# -*- coding: utf-8 -*-
# @Author  : Chat Automation System
# @Time    : 2024/12/26
# @Desc    : 知乎私信自动化系统
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
    from database.models import ZhihuContent, ZhihuChat
    from sqlalchemy import select, update, and_, or_
    from sqlalchemy.orm import selectinload
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保从项目根目录运行此脚本: python chat/zhihu_chat.py")
    sys.exit(1)


class ZhihuChatAutomation:
    """
    知乎私信自动化系统
    实现自动生成开场白并发送私信的功能
    """

    def __init__(self):
        self.browser_context: Optional[BrowserContext] = None
        self.playwright = None

    async def create_chat_table(self):
        """创建zhihu_chat表 - SQLAlchemy会自动创建"""
        # 表结构由SQLAlchemy ORM自动管理
        utils.logger.info("[ZhihuChatAutomation] zhihu_chat表创建完成 (SQLAlchemy自动管理)")

    async def add_chat_website_url_column(self):
        """在zhihu_content表中增加chat_website_url字段 - SQLAlchemy模型已定义"""
        # chat_website_url字段已在ZhihuContent模型中定义
        utils.logger.info("[ZhihuChatAutomation] chat_website_url字段检查完成 (SQLAlchemy模型已定义)")

    async def update_chat_website_urls(self):
        """更新zhihu_content表中的chat_website_url字段"""
        async with get_session() as session:
            # 查询所有没有chat_website_url的记录
            stmt = select(ZhihuContent).where(
                or_(ZhihuContent.chat_website_url.is_(None), ZhihuContent.chat_website_url == '')
            )
            result = await session.execute(stmt)
            contents = result.scalars().all()

            updated_count = 0
            for content in contents:
                if content.user_url_token:
                    content.chat_website_url = f"https://www.zhihu.com/people/{content.user_url_token}"
                    content.last_modify_ts = utils.get_current_time()
                    updated_count += 1

            await session.commit()
            utils.logger.info(f"[ZhihuChatAutomation] 更新了 {updated_count} 条记录的chat_website_url")

    async def create_chat_records_from_contents(self):
        """为zhihu_content表中的数据创建对应的zhihu_chat表记录"""
        async with get_session() as session:
            # 查询所有有source_keyword但在zhihu_chat表中没有对应记录的内容
            subquery = select(ZhihuChat.chat_id)
            stmt = select(ZhihuContent).where(
                and_(
                    ZhihuContent.source_keyword.isnot(None),
                    ZhihuContent.source_keyword != '',
                    ~ZhihuContent.content_id.in_(subquery)
                )
            )
            result = await session.execute(stmt)
            contents = result.scalars().all()

            created_count = 0
            for content in contents:
                chat_record = ZhihuChat(
                    chat_id=content.content_id,
                    source_keyword=content.source_keyword,
                    status="pending",
                    add_ts=utils.get_current_time(),
                    last_modify_ts=utils.get_current_time()
                )
                session.add(chat_record)
                created_count += 1

            await session.commit()
            utils.logger.info(f"[ZhihuChatAutomation] 创建了 {created_count} 条zhihu_chat记录")

    async def generate_chat_start_messages(self):
        """调用AI API生成开场白"""
        async with get_session() as session:
            # 查询所有还没有chat_start的记录，并关联ZhihuContent表获取更多信息
            stmt = select(ZhihuChat, ZhihuContent).join(
                ZhihuContent, ZhihuChat.chat_id == ZhihuContent.content_id
            ).where(
                and_(
                    or_(ZhihuChat.chat_start.is_(None), ZhihuChat.chat_start == ''),
                    ZhihuChat.source_keyword.isnot(None),
                    ZhihuChat.source_keyword != ''
                )
            ).limit(10)
            result = await session.execute(stmt)
            chat_content_pairs = result.all()

            for chat_record, content in chat_content_pairs:
                try:
                    # 构建包含对象内容的prompt
                    content_info = []
                    
                    # 添加关键词
                    content_info.append(f"搜索关键词：{chat_record.source_keyword}")
                    
                    # 添加用户昵称
                    if content.user_nickname:
                        content_info.append(f"对方昵称：{content.user_nickname}")
                    
                    # 添加内容类型和标题
                    if content.content_type:
                        content_info.append(f"内容类型：{content.content_type}")
                    if content.title:
                        content_info.append(f"内容标题：{content.title}")
                    
                    # 添加内容摘要（截取前200字，避免过长）
                    if content.content_text:
                        content_summary = content.content_text[:200] + "..." if len(content.content_text) > 200 else content.content_text
                        content_info.append(f"内容摘要：{content_summary}")
                    
                    # 添加互动数据
                    if content.voteup_count or content.comment_count:
                        engagement_info = []
                        if content.voteup_count:
                            engagement_info.append(f"{content.voteup_count}赞")
                        if content.comment_count:
                            engagement_info.append(f"{content.comment_count}评论")
                        if engagement_info:
                            content_info.append(f"互动情况：{', '.join(engagement_info)}")
                    
                    # 构建完整的prompt
                    content_str = "\n".join(content_info)
                    prompt = f"根据以下信息，生成一段友好的知乎私信开场白：\n\n{content_str}"

                    # chat_start = await self.call_qwen_api(prompt)
                    chat_start = await self.call_bigmodel_api(prompt)

                    if chat_start:
                        chat_record.chat_start = chat_start
                        chat_record.last_modify_ts = utils.get_current_time()
                        utils.logger.info(f"[ZhihuChatAutomation] 为chat_id {chat_record.chat_id} (用户:{content.user_nickname}) 生成开场白: {chat_start}")
                        await asyncio.sleep(1)  # 避免API调用过于频繁

                except Exception as e:
                    utils.logger.error(f"[ZhihuChatAutomation] 生成开场白失败 chat_id={chat_record.chat_id}: {e}")

            await session.commit()

    async def call_bigmodel_api(self, prompt: str) -> Optional[str]:
        """调用智谱AI API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的知乎私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 结合对方的内容特点，个性化定制 6. 字数控制在60字以内"}
            ]
            
            import concurrent.futures
            import asyncio
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, call_bigmodel, messages)
            if result and result.choices:
                return result.choices[0].message.content.strip()
    
            else:
                utils.logger.error(f"[ZhihuChatAutomation] 智谱AI API调用失败: {result}")
                return None

        except Exception as e:
            utils.logger.error(f"[ZhihuChatAutomation] 智谱AI API调用异常: {e}")
            return None

    async def call_qwen_api(self, prompt: str) -> Optional[str]:
        """调用通义千问API生成文本"""
        try:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "system", "content": "你是一个网络传道人，主要目的是传福音，请根据用户的需求，生成一段友好的知乎私信开场白，但不能暴露自己的身份。要求：1. 礼貌友好 2. 简洁自然 3. 带有福音性 4. 能够激发他人想交流的兴趣 5. 字数控制在50字以内"}
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
                utils.logger.error(f"[ZhihuChatAutomation] 通义千问API调用失败: {result}")
                return None

        except Exception as e:
            utils.logger.error(f"[ZhihuChatAutomation] 通义千问API调用异常: {e}")
            return None

    async def check_login_status(self, page: Page) -> bool:
        """检测当前页面是否已登录"""
        try:
            # 方法1: 检查URL是否包含登录相关参数（最快速）
            current_url = page.url
            if 'signin' in current_url.lower() or 'login' in current_url.lower() or 'register' in current_url.lower():
                utils.logger.warning(f"[ZhihuChatAutomation] 检测到未登录状态（URL包含登录信息: {current_url}）")
                return False

            # 方法2: 检查页面标题是否包含登录相关词汇
            page_title = await page.title()
            if '登录' in page_title or 'Sign in' in page_title or '注册' in page_title:
                utils.logger.warning(f"[ZhihuChatAutomation] 检测到未登录状态（页面标题: {page_title}）")
                return False

            # 方法3: 检查未登录标识（优先检测未登录，更可靠）
            not_logged_in_selectors = [
                # 登录页面的特定元素
                "a.SignFlow-accountInput",
                "button.SignFlow-submitButton",
                "button:has-text('登录知乎')",
                "button.SignFlow-submitButton:has-text('登录')",
                ".SignFlow-content",
                ".SignFlow-main"
            ]

            for selector in not_logged_in_selectors:
                try:
                    login_element = page.locator(selector).first
                    if await login_element.count() > 0 and await login_element.is_visible():
                        utils.logger.warning(f"[ZhihuChatAutomation] 检测到未登录状态（发现登录页面元素: {selector}）")
                        return False
                except:
                    continue

            # 方法4: 检查页面是否显示登录提示
            try:
                login_prompt = await page.locator("text=登录知乎").count()
                if login_prompt > 0:
                    utils.logger.warning("[ZhihuChatAutomation] 检测到未登录状态（发现登录提示）")
                    return False
            except:
                pass

            # 方法5: 检查是否有顶部导航栏的用户菜单（已登录时会有）
            logged_in_selectors = [
                # 顶部导航栏的用户菜单（最可靠的已登录标识）
                ".GlobalSideBar-navList .AppHeader-profile",
                ".AppHeader-profile",
                "[class*='AppHeader-profile']",
                
                # 顶部导航栏的消息图标（已登录时会有）
                ".GlobalSideBar .AppHeader-notifications",
                
                # 用户头像（在顶部导航栏）
                ".AppHeader-inner .Avatar",
                "[class*='AppHeader-inner'] .Avatar"
            ]

            for selector in logged_in_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        utils.logger.info(f"[ZhihuChatAutomation] 检测到已登录状态（发现: {selector}）")
                        return True
                except:
                    continue

            # 方法6: 检查localStorage中的登录状态（备用方案）
            try:
                login_status = await page.evaluate("() => localStorage.getItem('zse93') || localStorage.getItem('login') || localStorage.getItem('LOGIN_STATUS')")
                if login_status and '1' in str(login_status):
                    utils.logger.info("[ZhihuChatAutomation] 检测到已登录状态（localStorage验证）")
                    return True
            except:
                pass

            # 如果以上方法都无法确定，默认认为未登录（更安全）
            utils.logger.warning("[ZhihuChatAutomation] 无法确定登录状态，默认认为未登录")
            return False

        except Exception as e:
            utils.logger.warning(f"[ZhihuChatAutomation] 检测登录状态时出错: {e}，默认认为未登录")
            return False

    async def send_chat_messages(self):
        """使用Playwright自动化发送私信 - 循环处理所有符合条件的记录"""
        # 初始化Playwright浏览器
        await self.init_browser()

        try:
            while True:
                async with get_session() as session:
                    # 查询待发送的私信，每次处理1条
                    stmt = select(ZhihuChat, ZhihuContent).join(
                        ZhihuContent, ZhihuChat.chat_id == ZhihuContent.content_id
                    ).where(
                        and_(
                            ZhihuChat.status == 'pending',
                            ZhihuChat.chat_start.isnot(None),
                            ZhihuChat.chat_start != '',
                            ZhihuContent.chat_website_url.isnot(None),
                            ZhihuContent.chat_website_url != ''
                        )
                    ).limit(1)
                    result = await session.execute(stmt)
                    chat_content_pairs = result.all()

                    if not chat_content_pairs:
                        utils.logger.info("[ZhihuChatAutomation] 所有符合条件的私信都已处理完成")
                        break

                    chat_record, content = chat_content_pairs[0]
                    chat_id = chat_record.chat_id
                    chat_start = chat_record.chat_start
                    chat_url = content.chat_website_url

                    page = None
                    try:
                        utils.logger.info(f"[ZhihuChatAutomation] 开始处理私信 chat_id={chat_id}")

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

                        # 等待知乎页面的关键元素出现，或者使用时间等待
                        try:
                            # 尝试等待用户头像或用户名等关键元素
                            await page.wait_for_selector('.Avatar, .ProfileHeader, [class*="avatar"]', timeout=5000)
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
                            utils.logger.warning("[ZhihuChatAutomation] 检测到未登录状态")
                            utils.logger.info("=" * 80)
                            utils.logger.info("【重要提示】当前账号未登录，无法发送私信")
                            utils.logger.info("请按照以下步骤操作：")
                            utils.logger.info("1. 在打开的浏览器中手动登录知乎账号")
                            utils.logger.info("2. 登录成功后，本程序将自动继续执行")
                            utils.logger.info("=" * 80)

                            # 等待用户登录，每5秒检测一次登录状态
                            max_wait_time = 600  # 最多等待10分钟
                            wait_time = 0
                            check_interval = 5  # 每5秒检测一次

                            utils.logger.info("[ZhihuChatAutomation] 正在等待用户登录...")
                            while wait_time < max_wait_time:
                                await asyncio.sleep(check_interval)
                                wait_time += check_interval

                                # 重新检测登录状态
                                is_logged_in = await self.check_login_status(page)
                                if is_logged_in:
                                    utils.logger.info("[ZhihuChatAutomation] 检测到登录成功！继续执行...")
                                    break

                                # 每分钟提示一次
                                if wait_time % 60 == 0:
                                    utils.logger.info(f"[ZhihuChatAutomation] 已等待 {wait_time//60} 分钟，请尽快登录...")

                            if not is_logged_in:
                                raise Exception(f"等待登录超时（已等待 {max_wait_time//60} 分钟），程序终止。请重新运行程序并确保登录状态。")

                        # 先滚动页面，确保按钮可见且可点击
                        utils.logger.info("[ZhihuChatAutomation] 滚动页面以确保私信按钮可见")
                        try:
                            # 滚动到页面中部，避免固定Header遮挡
                            await page.evaluate('window.scrollTo(0, window.innerHeight)')
                            await asyncio.sleep(1)  # 等待页面稳定
                        except:
                            pass

                        # 查找私信按钮
                        # 根据完整HTML结构优化选择器
                        private_message_selectors = [
                            # 策略1: 通过MemberButtonGroup + ProfileButtonGroup容器 + 灰色按钮 + 文本定位（最精确）
                            ".MemberButtonGroup.ProfileButtonGroup button.Button--grey:has-text('发私信')",
                            ".MemberButtonGroup.ProfileButtonGroup button.Button--grey:has-text('私信')",

                            # 策略2: 通过MemberButtonGroup容器 + 灰色按钮 + 文本定位
                            ".MemberButtonGroup button.Button--grey:has-text('发私信')",
                            ".MemberButtonGroup button.Button--grey:has-text('私信')",

                            # 策略3: 通过ProfileButtonGroup容器 + 灰色按钮 + 文本定位
                            ".ProfileButtonGroup button.Button--grey:has-text('发私信')",
                            ".ProfileButtonGroup button.Button--grey:has-text('私信')",

                            # 策略4: 通过ProfileHeader-buttons容器 + 文本定位
                            ".ProfileHeader-buttons button:has-text('发私信')",
                            ".ProfileHeader-buttons button:has-text('私信')",

                            # 策略5: 通过Comments图标精确定位（配合Button类名）
                            "button.Button .Zi--Comments",
                            "button.Button svg.Zi--Comments",

                            # 策略6: 通过Button--grey + Button--withIcon组合定位
                            "button.Button--grey.Button--withIcon:has-text('发私信')",
                            "button.Button--grey.Button--withIcon:has-text('私信')",

                            # 策略7: 通过Button-zi图标类名定位
                            "button .Button-zi.Zi--Comments",
                            "button svg.Button-zi.Zi--Comments",

                            # 策略8: 通用的灰色按钮 + 文本定位
                            "button.Button--grey:has-text('发私信')",
                            "button.Button--grey:has-text('私信')",

                            # 策略9: 通过父容器span定位（发私信文本在span外）
                            ".ProfileHeader-buttons button.Button--grey.Button--withIcon",

                            # 策略10: 最通用的文本匹配（作为最后备选）
                            "button:has-text('发私信')",
                            "button:has-text('私信')"
                        ]

                        message_button = None
                        successful_selector = None

                        # 先等待页面按钮组加载完成
                        try:
                            await page.wait_for_selector('.MemberButtonGroup, .ProfileButtonGroup, .ProfileHeader-buttons', timeout=10000)
                            utils.logger.info("[ZhihuChatAutomation] 按钮组已加载")
                        except:
                            utils.logger.warning("[ZhihuChatAutomation] 等待按钮组超时，继续尝试查找")

                        for index, selector in enumerate(private_message_selectors, 1):
                            try:
                                utils.logger.info(f"[ZhihuChatAutomation] 尝试选择器 {index}/{len(private_message_selectors)}: {selector}")
                                
                                message_button = page.locator(selector).first
                                
                                # 检查元素是否存在
                                count = await message_button.count()
                                utils.logger.info(f"[ZhihuChatAutomation] 选择器匹配到 {count} 个元素")
                                
                                if count > 0:
                                    # 等待元素变为可见状态
                                    try:
                                        await message_button.wait_for(state='visible', timeout=3000)
                                        if await message_button.is_visible():
                                            successful_selector = selector
                                            utils.logger.info(f"[ZhihuChatAutomation] ✓ 成功找到私信按钮: {selector}")
                                            break
                                    except Exception as e:
                                        utils.logger.debug(f"[ZhihuChatAutomation] 选择器 {selector} 元素不可见: {e}")
                                        continue
                            except Exception as e:
                                utils.logger.debug(f"[ZhihuChatAutomation] 选择器 {selector} 失败: {e}")
                                continue

                        if message_button and successful_selector:
                            try:
                                # 再次滚动到按钮可见区域（确保按钮完全可见）
                                await message_button.scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)
                                
                                # 获取按钮的位置信息
                                bounding_box = await message_button.bounding_box()
                                if bounding_box:
                                    utils.logger.info(f"[ZhihuChatAutomation] 按钮位置: x={bounding_box['x']}, y={bounding_box['y']}, width={bounding_box['width']}, height={bounding_box['height']}")

                                # 检查按钮是否被禁用（可能未登录）
                                is_disabled = await message_button.is_disabled()
                                if is_disabled:
                                    raise Exception("私信按钮处于禁用状态，可能是因为未登录或已被关注")

                                # 尝试点击按钮
                                try:
                                    await message_button.click(timeout=5000)
                                except:
                                    # 如果普通点击失败，尝试使用强制点击
                                    utils.logger.warning("[ZhihuChatAutomation] 普通点击失败，尝试强制点击")
                                    await message_button.click(force=True, timeout=5000)
                                
                                await asyncio.sleep(2)  # 等待私信弹窗加载
                                utils.logger.info(f"[ZhihuChatAutomation] 成功点击私信按钮")
                            except Exception as click_error:
                                raise Exception(f"点击私信按钮失败: {click_error}")

                            # 找到输入框并输入消息
                            # 根据实际HTML结构优化选择器
                            input_selectors = [
                                # 策略1: 精确匹配textarea元素
                                "textarea.Input.i7cW1UcwT6ThdhTakqFm",

                                # 策略2: 通过Input类名定位
                                "textarea.Input",

                                # 策略3: 通过Input-wrapper类名定位
                                ".InputBox-input textarea",

                                # 策略4: 通用的textarea选择器
                                "textarea",

                                # 策略5: 通过Input-wrapper类名组合
                                ".Input-wrapper textarea",
                                ".Input-wrapper--multiline textarea"
                            ]

                            input_element = None
                            for selector in input_selectors:
                                try:
                                    input_element = page.locator(selector).first
                                    if await input_element.is_visible():
                                        utils.logger.info(f"[ZhihuChatAutomation] 找到输入框: {selector}")
                                        break
                                except:
                                    continue

                            if input_element:
                                await input_element.click()
                                await asyncio.sleep(0.5)
                                await input_element.fill(chat_start)
                                await asyncio.sleep(1)

                                # 找到发送按钮并点击
                                # 根据实际HTML结构优化选择器
                                send_selectors = [
                                    # 策略1: 精确匹配发送按钮（蓝色按钮）
                                    "button.InputBox-sendBtn:has-text('发送')",

                                    # 策略2: 通过类名组合定位
                                    "button.Button--primary.Button--blue:has-text('发送')",

                                    # 策略3: 通过InputBox-footer定位
                                    ".InputBox-footer button:has-text('发送')",

                                    # 策略4: 通用的文本匹配
                                    "button:has-text('发送')",
                                    "button:has-text('发送消息')",

                                    # 策略5: 通过类名
                                    ".InputBox-sendBtn"
                                ]

                                send_button = None
                                for selector in send_selectors:
                                    try:
                                        send_button = page.locator(selector).first
                                        if await send_button.is_visible():
                                            utils.logger.info(f"[ZhihuChatAutomation] 找到发送按钮: {selector}")
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

                                    utils.logger.info(f"[ZhihuChatAutomation] 成功发送私信 chat_id={chat_id}")

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
                        utils.logger.error(f"[ZhihuChatAutomation] 发送私信失败 chat_id={chat_id}: {e}")

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
        """初始化Playwright浏览器 - 使用Chrome"""
        self.playwright = await async_playwright().start()
        chromium = self.playwright.chromium

        # 使用现有的浏览器用户数据目录（如果有登录状态）
        user_data_dir = None
        if hasattr(base_config, 'USER_DATA_DIR') and base_config.USER_DATA_DIR:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", base_config.USER_DATA_DIR.replace('%s', 'zhihu'))
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
        utils.logger.info("[ZhihuChatAutomation] Playwright浏览器初始化完成")

    async def close_browser(self):
        """关闭Playwright浏览器"""
        try:
            if self.browser_context:
                await self.browser_context.close()
                self.browser_context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            utils.logger.info("[ZhihuChatAutomation] 浏览器已关闭")
        except Exception as e:
            utils.logger.error(f"[ZhihuChatAutomation] 关闭浏览器时出错: {e}")

    async def run_full_automation(self):
        """运行完整的自动化流程"""
        try:
            # 1. 创建必要的表结构
            await self.create_chat_table()
            await self.add_chat_website_url_column()

            # 2. 更新数据
            await self.update_chat_website_urls()
            await self.create_chat_records_from_contents()

            # 3. 生成开场白
            await self.generate_chat_start_messages()

            # 4. 发送私信
            await self.send_chat_messages()

            utils.logger.info("[ZhihuChatAutomation] 自动化流程完成")

        except Exception as e:
            utils.logger.error(f"[ZhihuChatAutomation] 自动化流程执行失败: {e}")
            raise


async def main():
    """主函数"""
    # 初始化数据库连接
    from database import db
    await db.init_db()

    chat_automation = ZhihuChatAutomation()
    await chat_automation.run_full_automation()


if __name__ == "__main__":
    asyncio.run(main())
    from database import db
