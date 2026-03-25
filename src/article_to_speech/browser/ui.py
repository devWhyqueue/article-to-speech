from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Error, Locator, Page

_AUDIO_LABEL_PATTERN = re.compile(
    r"read aloud|listen|play response|play audio|play message|voice|audio|speak",
    re.I,
)
_NON_AUDIO_LABEL_PATTERN = re.compile(
    r"copy|share|thumb|regenerate|edit|good response|bad response",
    re.I,
)


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
    for hover_target in (turn.locator("[data-message-author-role='assistant']").last, turn):
        if await hover_target.count():
            await hover_target.hover(timeout=10_000)
            await page.wait_for_timeout(500)
        button = await _matching_audio_button(turn)
        if button is not None:
            return button
        menu_item = page.get_by_role("menuitem", name=_AUDIO_LABEL_PATTERN)
        if await menu_item.count():
            return menu_item.first
    more_actions = turn.get_by_role("button", name=re.compile(r"more actions", re.I))
    if await more_actions.count():
        await more_actions.first.click(timeout=10_000)
        await page.wait_for_timeout(750)
        menu_item = page.get_by_role("menuitem", name=_AUDIO_LABEL_PATTERN)
        if await menu_item.count():
            return menu_item.first
    return None


async def _matching_audio_button(turn: Locator) -> Locator | None:
    buttons = turn.locator("button")
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        label_parts = [
            await button.get_attribute("aria-label") or "",
            await button.get_attribute("title") or "",
            await button.get_attribute("data-testid") or "",
            await button.inner_text(),
        ]
        label = " ".join(part.strip() for part in label_parts if part).strip()
        if not label or _NON_AUDIO_LABEL_PATTERN.search(label):
            continue
        if _AUDIO_LABEL_PATTERN.search(label):
            return button
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


async def create_project(page: Page, project_name: str) -> None:
    """Create the target ChatGPT project when it does not already exist."""
    if not await click_maybe(
        page, ["[data-testid='project-modal-trigger']"]
    ) and not await click_text(page, "New project"):
        raise Error(f"Unable to find or create ChatGPT project '{project_name}'.")
    await page.wait_for_timeout(1_000)
    filled = await fill_first(
        page,
        [
            "input[placeholder*='Project']",
            "input[name='name']",
            "input[type='text']",
        ],
        project_name,
    )
    if not filled:
        raise Error("Project creation dialog appeared but no project name input was found.")
    if not await click_text(page, "Create"):
        raise Error("Failed to confirm ChatGPT project creation.")
    await page.wait_for_timeout(2_000)


async def get_or_create_page(context: BrowserContext) -> Page:
    """Reuse the first persistent page or open a new one."""
    return context.pages[0] if context.pages else await context.new_page()


async def submit_prompt(page: Page) -> None:
    """Submit the current ChatGPT composer contents."""
    if not await click_maybe(
        page,
        ["button[data-testid='send-button']", "button[aria-label*='Send']"],
    ):
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(1_000)


async def goto_project_page(page: Page, project_name: str, retries: int = 5) -> bool:
    """Open the named ChatGPT project if it becomes visible in the current UI."""
    for _ in range(retries):
        project_locators = (
            page.locator("a[href*='/project/']").filter(has_text=project_name),
            page.locator("a[data-sidebar-item='true']").filter(has_text=project_name),
            page.get_by_role("link", name=project_name, exact=True),
            page.get_by_role("button", name=project_name, exact=True),
        )
        for locator in project_locators:
            if not await locator.count():
                continue
            href = await locator.first.get_attribute("href")
            if href:
                await page.goto(
                    urljoin(page.url, href),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            else:
                await locator.first.click(timeout=10_000)
                await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(1_000)
            if "/project" in page.url:
                return True
        await page.wait_for_timeout(1_000)
    return False
