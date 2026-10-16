import { expect, test, type Page } from "@playwright/test";

async function create(page: Page, topic: string, experts = 4) {
  await page.goto("/");
  await page.getByLabel("讨论话题").fill(topic);
  if (experts !== 4) await page.getByLabel("专家人数").selectOption(String(experts));
  await page.getByRole("button", { name: "创建并生成嘉宾" }).click();
  await expect(page.locator(".roster .cards article")).toHaveCount(experts + 1);
  const response = await page.request.get("/api/v1/discussions");
  const discussion = (await response.json()).find((item: { topic: string }) => item.topic === topic);
  return discussion.id as number;
}

test("real browser completes create, roster, SSE discussion, insights, summary and reload", async ({ page }) => {
  const topic = `浏览器闭环 ${Date.now()}`;
  const id = await create(page, topic);
  const roster = await (await page.request.get(`/api/v1/discussions/${id}/participants`)).json();
  expect(roster).toHaveLength(5);
  expect(roster.filter((p: { role: string }) => p.role === "host")).toHaveLength(1);
  for (const participant of roster) {
    const card = page.locator(".roster .cards article").filter({ hasText: participant.name });
    await expect(card).toContainText(participant.title);
    await expect(card).toContainText(participant.background);
    await expect(card).toContainText(participant.stance);
    await expect(card).toHaveCSS("border-top-color", "rgb(" + [1, 3, 5].map(n => parseInt(participant.color.slice(n, n + 2), 16)).join(", ") + ")");
  }
  expect(await (await page.request.get(`/api/v1/discussions/${id}/insights`)).json()).toEqual([]);
  await page.screenshot({ path: "../docs/evidence/roster-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "确认阵容，进入演播厅" }).click();
  expect((await (await page.request.post(`/api/v1/discussions/${id}/confirm`)).json()).status).toBe("confirmed");
  expect(await (await page.request.get(`/api/v1/discussions/${id}/participants`)).json()).toHaveLength(5);
  await page.getByRole("button", { name: "开始真实讨论" }).click();
  await expect(page.locator(".participants article.speaking")).toBeVisible();
  await expect(page.locator(".transcript article").first()).toContainText("围绕");
  await expect(page.locator(".insights .active")).toHaveCount(2, { timeout: 30_000 });
  await expect(page.locator(".pill")).toHaveText("讨论完成", { timeout: 30_000 });
  await expect(page.locator(".connection")).toHaveCount(0);
  await expect(page.locator(".transcript footer")).toContainText("主持人总结");
  await expect(page.locator(".connection")).toHaveCount(0);
  const messages = await (await page.request.get(`/api/v1/discussions/${id}/transcript`)).json();
  expect(messages.length).toBeGreaterThanOrEqual(5);
  expect(messages.at(-1).action).toBe("summary");
  for (const message of messages.slice(0, -1)) expect(message.content.length).toBeLessThanOrEqual(160);
  const wire = await (await page.request.get(`/api/v1/discussions/${id}/events`)).text();
  expect(wire).toContain("event: participant.hand_raised");
  expect(wire).toContain("event: insights.updated");
  expect(wire).toContain("event: discussion.summary");
  expect(messages.some((m: { content: string }) => m.content.includes("hand_raised"))).toBe(false);
  await page.screenshot({ path: "../docs/evidence/studio-completed-desktop.png", fullPage: true });
  await page.reload();
  await page.getByRole("button", { name: new RegExp(topic) }).click();
  await expect(page.locator(".pill")).toHaveText("讨论完成");
  await expect(page.locator(".transcript article")).toHaveCount(messages.length);
  await expect(page.locator(".transcript footer")).toContainText("主持人总结");
});

test("stopping one discussion does not affect another and both persist", async ({ page }) => {
  const a = `隔离甲 ${Date.now()}`;
  const aid = await create(page, a, 2);
  await page.getByRole("button", { name: "确认阵容，进入演播厅" }).click();
  await page.getByRole("button", { name: "开始真实讨论" }).click();
  await expect(page.locator(".transcript article").first()).toBeVisible();
  await page.getByRole("button", { name: "停止讨论" }).click();
  await expect(page.locator(".pill")).toHaveText("已停止");
  const stopped = await (await page.request.get(`/api/v1/discussions/${aid}/transcript`)).json();
  await page.getByRole("button", { name: /大厅/ }).click();
  const b = `隔离乙 ${Date.now()}`;
  const bid = await create(page, b, 2);
  await page.getByRole("button", { name: "确认阵容，进入演播厅" }).click();
  await page.getByRole("button", { name: "开始真实讨论" }).click();
  await expect(page.locator(".pill")).toHaveText("讨论完成", { timeout: 30_000 });
  const after = await (await page.request.get(`/api/v1/discussions/${aid}/transcript`)).json();
  expect(after).toHaveLength(stopped.length);
  const other = await (await page.request.get(`/api/v1/discussions/${bid}/transcript`)).json();
  expect(other.length).toBeGreaterThan(stopped.length);
  expect(after.every((m: { id: number }) => !other.some((n: { id: number }) => n.id === m.id))).toBe(true);
  const aEvents = await (await page.request.get(`/api/v1/discussions/${aid}/events`)).text();
  expect(aEvents).toContain(`"discussion_id": ${aid}`);
  expect(aEvents).not.toContain(`"discussion_id": ${bid}`);
  await page.reload();
  await page.getByRole("button", { name: new RegExp(a) }).click();
  await expect(page.locator(".pill")).toHaveText("已停止");
});

test("new transcript follows live messages but preserves the reader's history position", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await create(page, `滚动验收 ${Date.now()}`);
  await page.getByRole("button", { name: "确认阵容，进入演播厅" }).click();
  await page.getByRole("button", { name: "开始真实讨论" }).click();
  const transcript = page.locator(".transcript");
  await expect(transcript.locator("article")).toHaveCount(4, { timeout: 20_000 });
  await expect.poll(() => transcript.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await transcript.evaluate(el => { el.style.scrollBehavior = "auto"; el.scrollTop = 0; });
  await expect(transcript.locator("article")).toHaveCount(6, { timeout: 20_000 });
  expect(await transcript.evaluate(el => el.scrollTop)).toBeLessThan(30);
  await expect(page.locator(".pill")).toHaveText("讨论完成", { timeout: 20_000 });
});

test("validation, model failure and all three viewport layouts are usable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "创建并生成嘉宾" }).click();
  await expect(page.getByRole("alert")).toContainText("请输入讨论话题");
  const invalid = await page.request.post("/api/v1/discussions", { data: { topic: "x", expert_count: 7 } });
  expect(invalid.status()).toBe(422);
  await page.getByLabel("讨论话题").fill(`故障测试 ${Date.now()}`);
  await page.getByRole("button", { name: "创建并生成嘉宾" }).click();
  await expect(page.getByRole("alert")).toContainText("受控模型故障");
  const topic = `布局验收 ${Date.now()}`;
  const id = await create(page, topic);
  await page.getByRole("button", { name: "确认阵容，进入演播厅" }).click();
  for (const [name, width, height] of [["desktop", 1440, 900], ["phone", 390, 844], ["wide", 2560, 1440]] as const) {
    await page.setViewportSize({ width, height });
    await expect(page.locator(".grid")).toBeVisible();
    await expect(page.locator(".participants")).toBeVisible();
    await expect(page.locator(".transcript")).toBeVisible();
    await expect(page.locator(".insights")).toBeVisible();
    await expect(page.getByRole("button", { name: "开始真实讨论" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: `../docs/evidence/studio-confirmed-${name}.png`, fullPage: true });
  }
  expect((await (await page.request.get(`/api/v1/discussions/${id}`)).json()).status).toBe("confirmed");
});
