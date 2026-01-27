"""Browser tools - PlaywrightTool with headless support and BrowserExecutor."""
import base64
import logging
import os
from typing import Literal, cast

from hud.server import MCPRouter
from hud.tools.executors.base import BaseExecutor
from hud.tools.playwright import PlaywrightTool as BasePlaywrightTool
from hud.tools.types import ContentResult

logger = logging.getLogger(__name__)

router = MCPRouter()

# Read display dimensions from environment (same as HUD SDK computer tools)
DISPLAY_WIDTH = int(os.environ.get("DISPLAY_WIDTH", "1920"))
DISPLAY_HEIGHT = int(os.environ.get("DISPLAY_HEIGHT", "1080"))


# =============================================================================
# PlaywrightTool with headless support
# =============================================================================


class PlaywrightTool(BasePlaywrightTool):
    """PlaywrightTool that respects PLAYWRIGHT_HEADLESS environment variable."""

    async def _ensure_browser(self) -> None:
        """Ensure browser is launched and ready, respecting PLAYWRIGHT_HEADLESS env var."""
        if self._browser is None or not self._browser.is_connected():
            # Check if we should use headless mode
            headless_env = os.environ.get("PLAYWRIGHT_HEADLESS", "0")
            headless = headless_env.lower() in ("1", "true", "yes")
            
            if self._cdp_url:
                logger.info("Connecting to remote browser via CDP")
            else:
                logger.info(f"Launching Playwright browser (headless={headless})...")

            # Ensure DISPLAY is set for non-headless mode
            if not self._cdp_url and not headless:
                os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":1")

            if self._playwright is None:
                try:
                    from playwright.async_api import async_playwright
                    self._playwright = await async_playwright().start()
                except ImportError:
                    raise ImportError(
                        "Playwright is not installed. Please install with: pip install playwright"
                    ) from None

            # Connect via CDP URL or launch local browser
            if self._cdp_url:
                # Connect to remote browser via CDP
                self._browser = await self._playwright.chromium.connect_over_cdp(self._cdp_url)

                if self._browser is None:
                    raise RuntimeError("Failed to connect to remote browser")

                # Reuse existing context and page where possible
                contexts = self._browser.contexts
                if contexts:
                    self._browser_context = contexts[0]
                    existing_pages = self._browser_context.pages
                    if existing_pages:
                        self.page = existing_pages[0]
                else:
                    self._browser_context = await self._browser.new_context(
                        viewport={"width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT},
                        ignore_https_errors=True,
                    )
            else:
                # Launch local browser with headless setting from env var
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--disable-blink-features=AutomationControlled",
                        f"--window-size={DISPLAY_WIDTH},{DISPLAY_HEIGHT}",
                        "--window-position=0,0",
                        "--start-maximized",
                        "--disable-background-timer-throttling",
                        "--disable-backgrounding-occluded-windows",
                        "--disable-renderer-backgrounding",
                        "--disable-features=TranslateUI",
                        "--disable-ipc-flooding-protection",
                        "--disable-default-apps",
                        "--no-first-run",
                        "--disable-sync",
                        "--no-default-browser-check",
                    ],
                )

                if self._browser is None:
                    raise RuntimeError("Browser failed to initialize")

                self._browser_context = await self._browser.new_context(
                    viewport={"width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT},
                    ignore_https_errors=True,
                )

            if self._browser_context is None:
                raise RuntimeError("Browser context failed to initialize")

            # Reuse existing page if available, otherwise create new one
            pages = self._browser_context.pages
            if pages:
                self.page = pages[0]
                logger.info("Reusing existing browser page")
            else:
                self.page = await self._browser_context.new_page()
                logger.info("Created new browser page")
            logger.info("Playwright browser launched successfully")


# =============================================================================
# BrowserExecutor
# =============================================================================


PLAYWRIGHT_KEY_MAP = {
    "ctrl": "Control", "control": "Control", "alt": "Alt", "shift": "Shift",
    "meta": "Meta", "cmd": "Meta", "command": "Meta", "win": "Meta",
    "enter": "Enter", "return": "Enter", "tab": "Tab", "backspace": "Backspace",
    "delete": "Delete", "escape": "Escape", "esc": "Escape", "space": "Space",
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "pageup": "PageUp", "pagedown": "PageDown", "home": "Home", "end": "End",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6",
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
}


class BrowserExecutor(BaseExecutor):
    """Executor that performs actions within a browser viewport using Playwright."""

    def __init__(self, playwright_tool: PlaywrightTool, display_num: int | None = None):
        super().__init__(display_num)
        self.playwright_tool = playwright_tool

    def _map_key(self, key: str) -> str:
        return PLAYWRIGHT_KEY_MAP.get(key.lower().strip(), key)

    async def _ensure_page(self):
        await self.playwright_tool._ensure_browser()
        if not self.playwright_tool.page:
            raise RuntimeError("No browser page available")
        return self.playwright_tool.page

    async def screenshot(self) -> str | None:
        try:
            page = await self._ensure_page()
            screenshot_bytes = await page.screenshot(full_page=False)
            return base64.b64encode(screenshot_bytes).decode()
        except Exception as e:
            logger.error("Screenshot failed: %s", e)
            return None

    async def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: Literal["left", "right", "middle", "back", "forward"] = "left",
        pattern: list[int] | None = None,
        hold_keys: list[str] | None = None,
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()
            if x is None or y is None:
                return ContentResult(error="Coordinates required for click")

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.down(self._map_key(key))

            button_map = {"left": "left", "right": "right", "middle": "middle", "back": "left", "forward": "left"}
            click_button = cast(Literal["left", "right", "middle"], button_map[button])
            if pattern:
                for delay in pattern:
                    await page.mouse.click(x, y, button=click_button)
                    if delay > 0:
                        await page.wait_for_timeout(delay)
            else:
                await page.mouse.click(x, y, button=click_button)

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.up(self._map_key(key))

            result = ContentResult(output=f"Clicked at ({x}, {y})")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))

    async def write(
        self,
        text: str,
        enter_after: bool = False,
        hold_keys: list[str] | None = None,
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.down(self._map_key(key))

            await page.keyboard.type(text)
            if enter_after:
                await page.keyboard.press("Enter")

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.up(self._map_key(key))

            result = ContentResult(output=f"Typed: {text}")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))

    async def press(
        self,
        keys: list[str],
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()
            mapped_keys = [self._map_key(key) for key in keys]
            processed_keys = [k.upper() if len(k) == 1 and k.isalpha() and k.islower() else k for k in mapped_keys]
            key_combination = "+".join(processed_keys)
            await page.keyboard.press(key_combination)

            result = ContentResult(output=f"Pressed: {key_combination}")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))

    async def scroll(
        self,
        x: int | None = None,
        y: int | None = None,
        scroll_x: int | None = None,
        scroll_y: int | None = None,
        hold_keys: list[str] | None = None,
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()

            if x is None or y is None:
                viewport = page.viewport_size
                x = viewport["width"] // 2 if viewport else 400
                y = viewport["height"] // 2 if viewport else 300

            await page.mouse.move(x, y)
            await page.mouse.wheel(scroll_x or 0, scroll_y or 0)

            result = ContentResult(output=f"Scrolled by ({scroll_x}, {scroll_y})")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))

    async def move(
        self,
        x: int | None = None,
        y: int | None = None,
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()
            if x is None or y is None:
                return ContentResult(error="Coordinates required for move")

            await page.mouse.move(x, y)

            result = ContentResult(output=f"Moved to ({x}, {y})")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))

    async def drag(
        self,
        path: list[tuple[int, int]],
        button: Literal["left", "right", "middle"] = "left",
        hold_keys: list[str] | None = None,
        take_screenshot: bool = True,
    ) -> ContentResult:
        try:
            page = await self._ensure_page()
            if not path or len(path) < 2:
                return ContentResult(error="Path must have at least 2 points")

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.down(self._map_key(key))

            start_x, start_y = path[0]
            await page.mouse.move(start_x, start_y)
            await page.mouse.down(button=button)

            for x, y in path[1:]:
                await page.mouse.move(x, y)

            await page.mouse.up(button=button)

            if hold_keys:
                for key in hold_keys:
                    await page.keyboard.up(self._map_key(key))

            result = ContentResult(output=f"Dragged through {len(path)} points")
            if take_screenshot:
                result = result + ContentResult(base64_image=await self.screenshot())
            return result
        except Exception as e:
            return ContentResult(error=str(e))


__all__ = ["router", "PlaywrightTool", "BrowserExecutor"]
