from __future__ import annotations

import re

from playwright.async_api import Error, Locator, Page

_AUDIO_LABEL_PATTERN = re.compile(
    r"read aloud|listen|play response|play audio|play message|vorlesen|anh-ren|anhören|wiedergabe|antwort abspielen|audio abspielen|antwort anh-ren|antwort anhören",
    re.I,
)
_NON_AUDIO_LABEL_PATTERN = re.compile(
    r"copy|share|thumb|regenerate|edit|good response|bad response|voice|dictat|record",
    re.I,
)
_AUDIO_BUTTON_SELECTORS = [
    "button[data-testid*='audio']",
    "[role='menuitem'][data-testid*='audio']",
    "button[aria-label*='Read aloud']",
    "button[aria-label*='Listen']",
    "button[aria-label*='Play audio']",
    "button[aria-label*='Play response']",
    "button[aria-label*='Vorlesen']",
    "button[aria-label*='Anhören']",
    "button[aria-label*='Wiedergabe']",
    "[role='menuitem'][aria-label*='Read aloud']",
    "[role='menuitem'][aria-label*='Listen']",
    "[role='menuitem'][aria-label*='Play audio']",
    "[role='menuitem'][aria-label*='Play response']",
    "[role='menuitem'][aria-label*='Vorlesen']",
    "[role='menuitem'][aria-label*='Anhören']",
    "[role='menuitem'][aria-label*='Wiedergabe']",
]
_READ_ALOUD_ROLE_PATTERN = re.compile(
    r"^read aloud$|^listen$|^vorlesen$|^anhören$|^wiedergabe$",
    re.I,
)


async def locate_read_aloud_button(turn: Locator, page: Page) -> Locator | None:
    """Locate the read-aloud control for the latest assistant message."""
    for _ in range(3):
        await _scroll_chat_to_bottom(page)
        await _scroll_turn_into_view(turn)
        for hover_target in (turn.locator("[data-message-author-role='assistant']").last, turn):
            if await hover_target.count():
                try:
                    await hover_target.hover(timeout=10_000)
                except Error:
                    pass
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
        await page.wait_for_timeout(5_000)
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
    for role in ("menuitem", "button"):
        read_aloud = page.get_by_role(role, name=_READ_ALOUD_ROLE_PATTERN)
        if await read_aloud.count() and await read_aloud.first.is_visible():
            return read_aloud.first
    more_actions = await _find_more_actions_button(turn, page)
    if more_actions is None:
        return None
    await more_actions.click(timeout=10_000, force=True)
    await page.wait_for_timeout(1_500)
    for role in ("menuitem", "button"):
        read_aloud = page.get_by_role(role, name=_READ_ALOUD_ROLE_PATTERN)
        if await read_aloud.count() and await read_aloud.first.is_visible():
            return read_aloud.first
    return await _matching_audio_selector(page)


async def _scroll_turn_into_view(turn: Locator) -> None:
    if not await turn.count():
        return
    await turn.last.scroll_into_view_if_needed(timeout=10_000)
    await turn.page.wait_for_timeout(500)


async def _find_more_actions_button(turn: Locator, page: Page) -> Locator | None:
    candidates = (
        turn.locator("button[aria-label*='More actions'], button[aria-label*='Mehr Aktionen']"),
        turn.get_by_role("button", name=re.compile(r"more actions|mehr aktionen", re.I)),
        page.locator("main button[aria-label*='More actions'], main button[aria-label*='Mehr Aktionen']"),
        page.get_by_role("button", name=re.compile(r"more actions|mehr aktionen", re.I)),
    )
    for locator in candidates:
        for index in range(await locator.count()):
            button = locator.nth(index)
            if not await button.is_visible():
                continue
            label = " ".join(
                filter(None, [await button.get_attribute("aria-label"), await button.get_attribute("data-testid")])
            )
            if "actions" in label.lower() or "aktionen" in label.lower():
                return button
    return None


async def _scroll_chat_to_bottom(page: Page) -> None:
    scroll_button = page.locator("button.absolute.z-30")
    if await scroll_button.count() and await scroll_button.first.is_visible():
        await scroll_button.first.click(timeout=5_000)
        await page.wait_for_timeout(500)
