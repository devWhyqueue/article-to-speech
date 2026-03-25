from __future__ import annotations

import re

from playwright.async_api import Error, Locator, Page


async def click_text(page: Page, label: str) -> bool:
    """Click a visible button, link, or menu item matching the given label."""
    for role in ("button", "link", "menuitem"):
        locator = page.get_by_role(role, name=re.compile(f"^{re.escape(label)}$", re.I))
        if await _click_visible_locator(locator):
            return True
    text_locator = page.get_by_text(label, exact=True)
    if await _click_visible_locator(text_locator):
        return True
    return False


async def click_maybe(page: Page, selectors: list[str], *, force: bool = False) -> bool:
    """Click the first matching selector from a list of candidate selectors."""
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            await locator.first.click(timeout=10_000, force=force)
            return True
    return False


async def click_maybe_resilient(page: Page, selectors: list[str]) -> bool:
    """Click the first usable selector, retrying with force for overlay-heavy UIs."""
    for selector in selectors:
        locator = page.locator(selector)
        if await _click_visible_locator(locator):
            return True
    return False


async def _click_visible_locator(locator: Locator) -> bool:
    for index in range(await locator.count()):
        target = locator.nth(index)
        if not await target.is_visible():
            continue
        try:
            await target.click(timeout=10_000)
            return True
        except Error as error:
            if "intercepts pointer events" not in str(error):
                raise
            await target.click(timeout=10_000, force=True)
            return True
    return False


async def fill_first(page: Page, selectors: list[str], value: str) -> bool:
    """Fill the first matching input selector from a list of candidate selectors."""
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            await locator.first.fill(value)
            return True
    return False


async def find_editor(page: Page) -> Locator | None:
    """Locate the ChatGPT composer element."""
    selectors = [
        "#prompt-textarea",
        "textarea[placeholder*='Message']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "div[contenteditable='true'][role='textbox']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            return locator.first
    return None


async def wait_for_editor(page: Page, retries: int = 15) -> bool:
    """Wait for the ChatGPT composer to appear."""
    for _ in range(retries):
        if await find_editor(page) is not None:
            return True
        await page.wait_for_timeout(1_000)
    return False


async def fill_editor(editor: Locator, value: str) -> None:
    """Fill either a textarea-based or contenteditable-based ChatGPT editor."""
    tag_name = await editor.evaluate("(element) => element.tagName.toLowerCase()")
    if tag_name == "textarea":
        await editor.fill(value)
        return
    await editor.click()
    await editor.evaluate(
        """
        (element, incomingValue) => {
            element.textContent = incomingValue;
            element.dispatchEvent(new InputEvent("input", { bubbles: true }));
        }
        """,
        value,
    )


async def locate_read_aloud_button(turn: Locator, page: Page) -> Locator | None:
    """Locate the read-aloud control for the latest assistant message."""
    candidates = [
        turn.get_by_role("button", name=re.compile(r"read aloud|listen", re.I)),
        page.get_by_role("menuitem", name=re.compile(r"read aloud|listen", re.I)),
    ]
    for locator in candidates:
        if await locator.count():
            return locator.first
    more_actions = turn.get_by_role("button", name=re.compile(r"more actions", re.I))
    if await more_actions.count():
        await more_actions.first.click(timeout=10_000)
        await page.wait_for_timeout(750)
        menu_item = page.get_by_role("menuitem", name=re.compile(r"read aloud|listen", re.I))
        if await menu_item.count():
            return menu_item.first
    return None


async def open_new_chat(page: Page) -> bool:
    """Open a fresh ChatGPT chat from the current UI."""
    selectors = [
        "a[data-testid='create-new-chat-button']",
        "button[data-testid='create-new-chat-button']",
        "a[href='/']",
    ]
    if await click_maybe_resilient(page, selectors):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1_500)
        return True
    if await click_text(page, "New chat"):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1_500)
        return True
    return False
