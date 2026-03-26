from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.async_api import Error, Locator, Page

from article_to_speech.core.browser_runtime import is_project_page_url

_AUDIO_LABEL_PATTERN = re.compile(r"read aloud|listen|play response|play audio|play message", re.I)
_NON_AUDIO_LABEL_PATTERN = re.compile(
    r"copy|share|thumb|regenerate|edit|good response|bad response|voice|dictat|record",
    re.I,
)
_NEW_CHAT_SELECTORS = [
    "a[data-testid='create-new-chat-button']",
    "button[data-testid='create-new-chat-button']",
    "a[href$='/new']",
    "button[aria-label*='New chat']",
    "a[href='/']",
]
_AUDIO_BUTTON_SELECTORS = [
    "button[data-testid*='audio']",
    "[role='menuitem'][data-testid*='audio']",
    "button[aria-label*='Read aloud']",
    "button[aria-label*='Listen']",
    "button[aria-label*='Play audio']",
    "button[aria-label*='Play response']",
    "[role='menuitem'][aria-label*='Read aloud']",
    "[role='menuitem'][aria-label*='Listen']",
    "[role='menuitem'][aria-label*='Play audio']",
    "[role='menuitem'][aria-label*='Play response']",
]
_UI_SETTLE_MS = 5_000


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
    for _ in range(3):
        for hover_target in (turn.locator("[data-message-author-role='assistant']").last, turn):
            if await hover_target.count():
                await hover_target.hover(timeout=10_000)
                await page.wait_for_timeout(1_000)
            menu_item = await _open_more_actions_and_find_read_aloud(turn, page)
            if menu_item is not None:
                return menu_item
            button = await _matching_audio_button(turn)
            if button is not None:
                return button
            page_button = await _matching_audio_button(page.locator("main"))
            if page_button is not None:
                return page_button
            selector_button = await _matching_audio_selector(page)
            if selector_button is not None:
                return selector_button
        await settle_chatgpt_ui(page)
    return None


async def _matching_audio_button(turn: Locator) -> Locator | None:
    buttons = turn.locator("button, [role='button'], [role='menuitem']")
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        if not await button.is_visible():
            continue
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


async def _matching_audio_selector(page: Page) -> Locator | None:
    for selector in _AUDIO_BUTTON_SELECTORS:
        locator = page.locator(selector)
        if await locator.count() and await locator.first.is_visible():
            return locator.first
    for role in ("button", "menuitem"):
        locator = page.get_by_role(role, name=_AUDIO_LABEL_PATTERN)
        if await locator.count() and await locator.first.is_visible():
            return locator.first
    return None


async def _open_more_actions_and_find_read_aloud(turn: Locator, page: Page) -> Locator | None:
    more_actions = turn.get_by_role("button", name=re.compile(r"more actions", re.I))
    if not await more_actions.count():
        more_actions = page.get_by_role("button", name=re.compile(r"more actions", re.I))
    if not await more_actions.count():
        return None
    await more_actions.last.click(timeout=10_000)
    await page.wait_for_timeout(1_500)
    for role in ("menuitem", "button"):
        read_aloud = page.get_by_role(role, name=re.compile(r"^read aloud$|^listen$", re.I))
        if await read_aloud.count() and await read_aloud.first.is_visible():
            return read_aloud.first
    return await _matching_audio_selector(page)


async def open_new_chat(page: Page) -> bool:
    """Open a fresh ChatGPT chat from the current UI."""
    if await click_maybe_resilient(page, _NEW_CHAT_SELECTORS):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await settle_chatgpt_ui(page)
        return True
    if await click_text(page, "New chat"):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await settle_chatgpt_ui(page)
        return True
    project_root_url = _project_root_url(page.url)
    if project_root_url is not None and page.url != project_root_url:
        await page.goto(project_root_url, wait_until="domcontentloaded", timeout=60_000)
        await settle_chatgpt_ui(page)
        return True
    return False


async def open_workspace_root(page: Page) -> bool:
    """Return the active ChatGPT tab to the root workspace without spawning a new tab."""
    if page.url.rstrip("/") == "https://chatgpt.com":
        return True
    if await click_text(page, "ChatGPT"):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await settle_chatgpt_ui(page)
        return page.url.rstrip("/") == "https://chatgpt.com"
    if await click_maybe_resilient(page, ["a[href='/']", "nav a[href='/']"]):
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await settle_chatgpt_ui(page)
        return page.url.rstrip("/") == "https://chatgpt.com"
    return False


async def has_project_chat_controls(page: Page) -> bool:
    """Return whether the current project page exposes a composer or new-chat control."""
    if await find_editor(page) is not None:
        return True
    return await any_visible(page, _NEW_CHAT_SELECTORS)


async def submit_prompt(page: Page) -> None:
    """Submit the current ChatGPT composer contents."""
    if not await click_maybe(
        page,
        ["button[data-testid='send-button']", "button[aria-label*='Send']"],
    ):
        await page.keyboard.press("Enter")
    await settle_chatgpt_ui(page)


async def goto_project_page(page: Page, project_name: str, retries: int = 5) -> bool:
    """Open the named ChatGPT project if it becomes visible in the current UI."""
    project_name_pattern = re.compile(re.escape(project_name), re.I)
    for _ in range(retries):
        project_locators = (
            page.locator("a[href*='/g/g-p-']").filter(has_text=project_name_pattern),
            page.locator("a[href*='/project/']").filter(has_text=project_name),
            page.locator("[data-sidebar-item='true']").filter(has_text=project_name_pattern),
            page.locator("a[data-sidebar-item='true']").filter(has_text=project_name),
            page.get_by_role("link", name=project_name_pattern),
            page.get_by_role("button", name=project_name_pattern),
        )
        for locator in project_locators:
            if not await locator.count():
                continue
            if await locator.first.is_visible():
                await locator.first.click(timeout=10_000)
                await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            else:
                href = await locator.first.get_attribute("href")
                if not href:
                    continue
                await page.goto(
                    urljoin(page.url, href),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            await settle_chatgpt_ui(page)
            if is_project_page_url(page.url):
                return True
        await settle_chatgpt_ui(page)
    return False


def _project_root_url(url: str) -> str | None:
    if "/g/g-p-" in url:
        return url.partition("/c/")[0].rstrip("/")
    if "/project/" in url:
        prefix, _, suffix = url.partition("/project/")
        project_id = suffix.split("/", 1)[0]
        if project_id:
            return f"{prefix}/project/{project_id}"
    return None


async def any_visible(page: Page, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() and await locator.first.is_visible():
            return True
    return False


async def settle_chatgpt_ui(page: Page) -> None:
    """Pause between sensitive ChatGPT interactions so the UI can fully settle."""
    await page.wait_for_timeout(_UI_SETTLE_MS)
