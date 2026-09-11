"""Real browser checks for offline Swagger, help dialogs and the operator guide."""

from urllib.parse import urljoin, urlsplit

from playwright.sync_api import expect


def watch_documentation(context):
    errors, external = [], []
    context.add_init_script(
        "window.cspViolations = []; document.addEventListener('securitypolicyviolation', e => window.cspViolations.push(e.violatedDirective + ': ' + e.blockedURI));"
    )
    context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))

    def local_only(route):
        target = urlsplit(route.request.url)
        if target.scheme in ("http", "https") and target.hostname not in ("127.0.0.1", "localhost", "::1"):
            external.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    context.route("**/*", local_only)
    return errors, external


def public_documentation(context, page, output):
    expect(page.get_by_role("link", name="API仕様（Swagger UI）")).to_be_visible()
    with page.expect_popup() as popup:
        page.get_by_role("link", name="API仕様（Swagger UI）").click()
    docs = popup.value
    schema = docs.request.get(urljoin(page.url, "/admin/openapi.json")).json()
    operation_count = sum(len(operations) for operations in schema["paths"].values())
    expect(docs.locator(".opblock")).to_have_count(operation_count)
    assert docs.evaluate("window.ui.getConfigs().supportedSubmitMethods.length") == 0
    assert docs.evaluate("window.ui.getConfigs().validatorUrl") is None
    result = docs.locator("#operations-Challenge-submitResult")
    result.locator(".opblock-summary").click()
    expect(result.locator(".opblock-body")).to_contain_text("metadata")
    expect(result.locator(".opblock-body")).to_contain_text("replay")
    expect(docs.get_by_role("button", name="Try it out")).to_have_count(0)
    assert not docs.evaluate("window.cspViolations"), docs.evaluate("window.cspViolations")
    docs.screenshot(path=str(output / "swagger-ui.png"))
    docs.get_by_role("navigation", name="ドキュメントメニュー").get_by_role("link", name="図付き運用ガイド").click()
    expect(docs.get_by_role("heading", name="「予約の締切」と「提出の猶予」を分ける")).to_be_visible()
    expect(docs.locator("figure")).to_have_count(7)
    for value, expected in (
        ("420", "受付期限 21:07:00"),
        ("0", "受付期限 21:00:00"),
        ("604800", "受付期限 7日後 21:00:00"),
        ("-1", "0～604800の整数を入力してください"),
    ):
        docs.get_by_label("提出猶予（秒）", exact=True).fill(value)
        expect(docs.locator("#example-deadline")).to_have_text(expected)
    docs.get_by_label("提出猶予（秒）", exact=True).fill("300")
    docs.locator("#deadlines").screenshot(path=str(output / "guide-deadlines.png"))
    # Every help link points to a real section, including explanations added later.
    guide_ids = docs.locator("section[id]").evaluate_all("nodes => nodes.map(node => node.id)")
    topics = page.evaluate("Object.values(window.JBSL_HELP).map(entry => entry[1])")
    assert set(topics) <= set(guide_ids)
    docs.set_viewport_size({"width": 390, "height": 844})
    docs.goto(docs.url.split("#")[0] + "#refunds")
    expect(docs.get_by_role("heading", name="「対象外の受理」と「提出の拒否」は違う")).to_be_visible()
    assert docs.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    docs.screenshot(path=str(output / "guide-mobile.png"))
    assert not docs.evaluate("window.cspViolations")
    docs.close()


def settings_help(page, output):
    expect(page.get_by_role("link", name="API仕様（Swagger UI）")).to_be_visible()
    trigger = page.get_by_role("button", name="終了後の提出猶予（秒）の説明", exact=True)
    trigger.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="終了後の提出猶予（秒）", exact=True)
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("予約時に固定")
    expect(dialog.get_by_role("link")).to_have_attribute("href", "/admin/guide/#deadlines")
    page.screenshot(path=str(output / "admin-help.png"))
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    checkbox = page.get_by_role("checkbox", name="開始前の失敗", exact=False)
    previous = checkbox.is_checked()
    page.get_by_role("button", name="開始前の失敗の説明", exact=True).click()
    expect(page.get_by_role("dialog", name="開始前の失敗", exact=True)).to_be_visible()
    page.get_by_role("button", name="説明を閉じる", exact=True).click()
    assert checkbox.is_checked() == previous, "Opening help changed a refund setting"
    assert page.locator("#content input, #content select").evaluate_all(
        "nodes => nodes.every(node => node.closest('.field-help')?.querySelector('.help-button'))"
    ), "A setting is missing contextual help"
    assert not page.evaluate("window.cspViolations")


def submission_help(page):
    page.get_by_role("button", name="取消・復元の説明", exact=True).click()
    expect(page.get_by_role("dialog", name="取消・復元", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="提出結果", exact=True)).to_be_visible()
