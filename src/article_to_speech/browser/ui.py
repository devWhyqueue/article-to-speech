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
