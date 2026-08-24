async (page) => {
  const rootUrl = "https://www.thinkingai.cn/skills/";
  const robotsUrl = "https://www.thinkingai.cn/robots.txt";
  const sitemapUrl = "https://www.thinkingai.cn/sitemap.xml";
  const categories = [
    "付费分析", "游戏分析", "用户分析", "数据分析", "异常诊断", "舆情分析",
    "数据工程", "数据采集", "运营分析", "Agent", "知识库管理",
  ];

  const robotsResponse = await page.request.get(robotsUrl);
  const robotsText = await robotsResponse.text();
  const robotsValid = robotsResponse.status() === 200
    && robotsText.includes("Disallow: /backend/")
    && robotsText.includes("Disallow: /cj-booth/")
    && robotsText.includes(`Sitemap: ${sitemapUrl}`);
  if (!robotsValid) {
    throw new Error("approved robots boundary changed");
  }

  await page.goto(rootUrl, {waitUntil: "domcontentloaded"});
  await page.locator('main a[href^="/skills/"]').first().waitFor();
  const catalog = await page.locator('main a[href^="/skills/"]').evaluateAll(
    (links, knownCategories) => links.map((link) => ({
      source_id: link.getAttribute("href").split("/").filter(Boolean).at(-1),
      canonical_url: new URL(link.getAttribute("href"), location.origin).href,
      title: link.querySelector("h3")?.textContent?.trim() || "",
      source_categories: [...link.querySelectorAll("span")]
        .map((item) => item.textContent?.trim())
        .filter((item) => knownCategories.includes(item)),
    })),
    categories,
  );
  if (catalog.length > 1000) {
    throw new Error("catalog exceeds the bounded observation budget");
  }

  const categoryCounts = await page.locator("main button").evaluateAll(
    (buttons, knownCategories) => Object.fromEntries(
      buttons.map((button) => button.textContent?.trim() || "")
        .filter((text) => knownCategories.some((category) => text.startsWith(category)))
        .map((text) => {
          const category = knownCategories.find((candidate) => text.startsWith(candidate));
          return [category, Number(text.slice(category.length).trim())];
        }),
    ),
    categories,
  );
  const paginationUrls = await page.locator('main a[href*="page"]').evaluateAll(
    (links) => links.map((link) => new URL(link.getAttribute("href"), location.origin).href),
  );

  const items = [];
  for (const item of catalog) {
    const response = await page.goto(item.canonical_url, {waitUntil: "domcontentloaded"});
    await page.locator("main h1").first().waitFor();
    const detail = await page.evaluate(async () => {
      const normalized = (document.querySelector("main")?.innerText || "")
        .replace(/\s+/g, " ").trim();
      const digest = await crypto.subtle.digest(
        "SHA-256", new TextEncoder().encode(normalized),
      );
      return {
        content_sha256: [...new Uint8Array(digest)]
          .map((value) => value.toString(16).padStart(2, "0")).join(""),
        h1: document.querySelector("main h1")?.textContent
          ?.replace(/\s+/g, " ").trim() || "",
        declared_canonical_url: document.querySelector('link[rel="canonical"]')?.href || "",
      };
    });
    items.push({
      ...item,
      http_status: response?.status() || 0,
      final_url: page.url(),
      ...detail,
    });
    await page.waitForTimeout(250);
  }

  const sitemapResponse = await page.request.get(sitemapUrl);
  const sitemapText = await sitemapResponse.text();
  const sitemapSkillUrls = [
    ...sitemapText.matchAll(/<loc>(https:\/\/www\.thinkingai\.cn\/skills\/[^<]+)<\/loc>/g),
  ].map((match) => match[1]).filter((url) => url !== rootUrl).sort();
  const catalogUrls = new Set(catalog.map((item) => item.canonical_url));
  return {
    observed_at: new Date().toISOString(),
    root_url: rootUrl,
    robots_status: "allowed_except_backend_and_cj_booth",
    category_counts: categoryCounts,
    pagination_urls: paginationUrls.sort(),
    sitemap_skill_count: sitemapSkillUrls.length,
    sitemap_orphans: sitemapSkillUrls.filter((url) => !catalogUrls.has(url)),
    missing_from_sitemap: [...catalogUrls]
      .filter((url) => !sitemapSkillUrls.includes(url)).sort(),
    items: items.sort((left, right) => left.source_id.localeCompare(right.source_id)),
  };
}
