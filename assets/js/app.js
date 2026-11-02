/* Victoria Homewear & Pyjamas — storefront (vanilla JS, no build step) */
(() => {
  "use strict";

  const C = window.STORE_CONFIG;
  const PRODUCTS = window.PRODUCTS;
  const CATS = window.CATEGORIES;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const app = $("#app");

  /* ---------------- helpers ---------------- */
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => `${Math.round(n).toLocaleString("fr-DZ").replace(/ | /g, " ")} ${C.currency}`;
  const byId = (id) => PRODUCTS.find((p) => p.id === id);
  const catName = (id) => (CATS.find((c) => c.id === id) || {}).name || "";
  const discount = (p) => (p.oldPrice ? Math.round((1 - p.price / p.oldPrice) * 100) : 0);

  const store = {
    get(k, d) {
      try { const v = localStorage.getItem("victoria:" + k); return v ? JSON.parse(v) : d; } catch { return d; }
    },
    set(k, v) {
      try { localStorage.setItem("victoria:" + k, JSON.stringify(v)); } catch { /* storage unavailable */ }
    },
  };

  let cart = store.get("cart", []); // [{id,size,qty}]
  let wish = store.get("wish", []); // [id]

  const saveCart = () => { store.set("cart", cart); renderCartUI(); };
  const saveWish = () => { store.set("wish", wish); updateBadges(); };

  const cartLines = () =>
    cart.map((l) => ({ ...l, product: byId(l.id) })).filter((l) => l.product);
  const subtotal = () => cartLines().reduce((s, l) => s + l.product.price * l.qty, 0);
  const cartQty = () => cart.reduce((s, l) => s + l.qty, 0);

  function addToCart(id, size, qty = 1) {
    const line = cart.find((l) => l.id === id && l.size === size);
    if (line) line.qty = Math.min(line.qty + qty, 20);
    else cart.push({ id, size, qty });
    saveCart();
    toast(`تمت إضافة «${byId(id).name}» إلى السلة ✨`);
    bump($("#cartBtn"));
  }

  function toggleWish(id) {
    wish = wish.includes(id) ? wish.filter((w) => w !== id) : [...wish, id];
    saveWish();
    $$(`[data-wish="${id}"]`).forEach((b) => b.classList.toggle("on", wish.includes(id)));
    toast(wish.includes(id) ? "أضيفت إلى المفضلة ♥" : "أزيلت من المفضلة");
  }

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }
  const bump = (el) => { if (!el) return; el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); };

  const stars = (r) => {
    const full = Math.round(r);
    return `<span class="stars" aria-label="${r} من 5">${"★".repeat(full)}<span class="dim">${"★".repeat(5 - full)}</span></span>`;
  };

  /* ---------------- components ---------------- */
  const badgeHTML = (p) => {
    if (p.badge === "sale" || p.oldPrice) return `<span class="badge badge--sale">-${discount(p)}%</span>`;
    if (p.badge === "new") return `<span class="badge badge--new">جديد</span>`;
    if (p.badge === "best") return `<span class="badge badge--best">الأكثر مبيعاً</span>`;
    return "";
  };

  const card = (p) => `
    <article class="card reveal">
      <a href="#/product/${p.id}" class="card__media" aria-label="${esc(p.name)}">
        <img src="${p.image}" alt="${esc(p.name)}" loading="lazy" width="600" height="750" />
        ${badgeHTML(p)}
      </a>
      <button class="wish ${wish.includes(p.id) ? "on" : ""}" data-wish="${p.id}" aria-label="أضيفي إلى المفضلة">
        <svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-9.2-9A5 5 0 0 1 12 6a5 5 0 0 1 9.2 5C19 15.6 12 20 12 20z"/></svg>
      </button>
      <div class="card__body">
        <span class="card__cat">${catName(p.category)}</span>
        <h3 class="card__title"><a href="#/product/${p.id}">${esc(p.name)}</a></h3>
        <div class="card__meta">${stars(p.rating)} <small>(${p.reviews})</small></div>
        <div class="card__foot">
          <div class="price">
            <strong>${money(p.price)}</strong>
            ${p.oldPrice ? `<del>${money(p.oldPrice)}</del>` : ""}
          </div>
          <button class="btn btn--icon" data-quick="${p.id}" aria-label="أضيفي إلى السلة">
            <svg viewBox="0 0 24 24"><path d="M5 8h14l-1.2 11.2a2 2 0 0 1-2 1.8H8.2a2 2 0 0 1-2-1.8z"/><path d="M12 11v6M9 14h6"/></svg>
          </button>
        </div>
      </div>
    </article>`;

  const grid = (list) =>
    list.length
      ? `<div class="grid">${list.map(card).join("")}</div>`
      : `<div class="empty"><p>لا توجد منتجات مطابقة 🌸</p><a class="btn btn--gold" href="#/shop">تصفحي كل المنتجات</a></div>`;

  const sectionHead = (title, sub, link) => `
    <div class="section__head">
      <div><span class="eyebrow">${sub}</span><h2>${title}</h2></div>
      ${link ? `<a class="link-more" href="${link}">عرض الكل ←</a>` : ""}
    </div>`;

  /* ---------------- pages ---------------- */
  function pageHome() {
    const best = PRODUCTS.filter((p) => p.badge === "best" || p.rating >= 4.9).slice(0, 4);
    const fresh = PRODUCTS.filter((p) => p.badge === "new").slice(0, 4);
    const sale = PRODUCTS.filter((p) => p.oldPrice);
    return `
    <section class="hero">
      <div class="hero__glow"></div>
      <div class="container hero__inner">
        <div class="hero__text">
          <span class="eyebrow">مجموعة ${new Date().getFullYear()} الجديدة</span>
          <h1>أناقتكِ <span class="gold">تبدأ</span> من البيت</h1>
          <p class="script hero__script">${esc(C.slogan)}</p>
          <p class="hero__lead">بيجامات ساتان، روبات وقمصان نوم فاخرة بتفاصيل راقية ولمسة ملكية. لأنكِ تستحقين الدلال في كل لحظة.</p>
          <div class="hero__cta">
            <a href="#/shop" class="btn btn--gold btn--lg">تسوّقي الآن</a>
            <a href="#/shop?cat=robes" class="btn btn--ghost btn--lg">اكتشفي الروبات</a>
          </div>
          <ul class="hero__stats">
            <li><strong>+2000</strong><span>زبونة سعيدة</span></li>
            <li><strong>58</strong><span>ولاية نوصل لها</span></li>
            <li><strong>4.9★</strong><span>تقييم الزبائن</span></li>
          </ul>
        </div>
        <div class="hero__art">
          <div class="hero__ring"></div>
          <img src="assets/img/logo.webp" alt="Victoria Homewear & Pyjamas" width="560" height="560" fetchpriority="high" />
        </div>
      </div>
    </section>

    <section class="perks">
      <div class="container perks__grid">
        <div class="perk"><span>🚚</span><div><strong>توصيل لكل الولايات</strong><small>للمنزل أو المكتب</small></div></div>
        <div class="perk"><span>💵</span><div><strong>الدفع عند الاستلام</strong><small>بدون أي دفع مسبق</small></div></div>
        <div class="perk"><span>🔄</span><div><strong>استبدال سهل</strong><small>خلال 7 أيام</small></div></div>
        <div class="perk"><span>👑</span><div><strong>جودة فاخرة</strong><small>ساتان ناعم ومتين</small></div></div>
      </div>
    </section>

    <section class="section container">
      ${sectionHead("تسوّقي حسب الفئة", "Collections")}
      <div class="cats">
        ${CATS.map((c) => {
          const p = PRODUCTS.find((x) => x.category === c.id);
          const n = PRODUCTS.filter((x) => x.category === c.id).length;
          return `<a class="cat reveal" href="#/shop?cat=${c.id}">
            <img src="${p ? p.image : ""}" alt="" loading="lazy" />
            <div class="cat__label"><span>${c.icon}</span><strong>${c.name}</strong><small>${n} منتجات</small></div>
          </a>`;
        }).join("")}
      </div>
    </section>

    <section class="section container">
      ${sectionHead("الأكثر طلباً", "Best Sellers", "#/shop?sort=popular")}
      ${grid(best)}
    </section>

    <section class="promo">
      <div class="container promo__inner reveal">
        <div>
          <span class="eyebrow">عرض خاص</span>
          <h2>توصيل <span class="gold">مجاني</span> للطلبات فوق ${money(C.freeShippingFrom)}</h2>
          <p>دللي نفسك أو أهدي من تحبين قطعة من Victoria — مغلفة بعناية في علبة هدية أنيقة.</p>
          <a class="btn btn--gold" href="#/shop">ابدئي التسوق</a>
        </div>
        <div class="promo__imgs">
          ${sale.slice(0, 2).map((p) => `<a href="#/product/${p.id}"><img src="${p.image}" alt="${esc(p.name)}" loading="lazy" /><span>-${discount(p)}%</span></a>`).join("")}
        </div>
      </div>
    </section>

    <section class="section container">
      ${sectionHead("وصل حديثاً", "New Arrivals", "#/shop?sort=new")}
      ${grid(fresh)}
    </section>

    <section class="section container">
      ${sectionHead("آراء زبوناتنا", "Testimonials")}
      <div class="reviews">
        ${[
          ["سارة", "قسنطينة", "القماش ناعم جداً والقصة مثالية، والتوصيل كان سريع. أكيد رح نعاود نطلب!"],
          ["أمينة", "الجزائر", "الروب العنابي تحفة! جاء مغلف بطريقة راقية كأنها هدية. شكراً Victoria 💗"],
          ["ليندة", "وهران", "طلبت بيجامة لأختي هدية وعجبتها بزاف. الجودة أحسن من الصور."],
        ].map(([n, w, t]) => `
          <figure class="review reveal">
            ${stars(5)}
            <blockquote>«${t}»</blockquote>
            <figcaption><span class="avatar">${n[0]}</span><span><strong>${n}</strong><small>${w}</small></span></figcaption>
          </figure>`).join("")}
      </div>
    </section>

    <section class="section container">
      <div class="insta reveal">
        <div>
          <span class="eyebrow">تابعينا</span>
          <h2>انضمي إلى عائلة Victoria</h2>
          <p>إطلالات جديدة، عروض حصرية ومسابقات كل أسبوع على صفحاتنا.</p>
        </div>
        <div class="insta__btns">
          <a class="btn btn--gold" href="${C.instagram}" target="_blank" rel="noopener">Instagram</a>
          <a class="btn btn--ghost" href="${C.tiktok}" target="_blank" rel="noopener">TikTok</a>
          <a class="btn btn--ghost" href="${C.facebook}" target="_blank" rel="noopener">Facebook</a>
        </div>
      </div>
    </section>`;
  }

  function pageShop(params) {
    const cat = params.get("cat") || "all";
    const q = (params.get("q") || "").trim();
    const sort = params.get("sort") || "featured";
    const size = params.get("size") || "";

    let list = PRODUCTS.filter((p) => cat === "all" || p.category === cat);
    if (q) {
      const nq = q.toLowerCase();
      list = list.filter((p) =>
        [p.name, p.color, p.description, catName(p.category)].join(" ").toLowerCase().includes(nq));
    }
    if (size) list = list.filter((p) => p.sizes.some((s) => s.split("/").includes(size)));
    const sorters = {
      featured: () => 0,
      popular: (a, b) => b.reviews - a.reviews,
      new: (a, b) => (b.badge === "new") - (a.badge === "new"),
      "price-asc": (a, b) => a.price - b.price,
      "price-desc": (a, b) => b.price - a.price,
      rating: (a, b) => b.rating - a.rating,
    };
    list = [...list].sort(sorters[sort] || sorters.featured);

    const link = (over) => {
      const p = new URLSearchParams(params);
      Object.entries(over).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
      const s = p.toString();
      return "#/shop" + (s ? "?" + s : "");
    };
    const title = q ? `نتائج البحث عن «${esc(q)}»` : cat === "all" ? "كل المنتجات" : catName(cat);

    return `
    <section class="page-hero">
      <div class="container">
        <nav class="crumbs"><a href="#/">الرئيسية</a> / <span>المتجر</span></nav>
        <h1>${title}</h1>
        <p>${list.length} منتج</p>
      </div>
    </section>
    <section class="container shop">
      <div class="toolbar">
        <div class="chips" role="tablist">
          <a class="chip ${cat === "all" ? "on" : ""}" href="${link({ cat: "" })}">الكل</a>
          ${CATS.map((c) => `<a class="chip ${cat === c.id ? "on" : ""}" href="${link({ cat: c.id })}">${c.icon} ${c.name}</a>`).join("")}
        </div>
        <div class="toolbar__right">
          <label class="select">
            <span>المقاس</span>
            <select data-param="size">
              <option value="">الكل</option>
              ${["S", "M", "L", "XL", "XXL"].map((s) => `<option ${s === size ? "selected" : ""}>${s}</option>`).join("")}
            </select>
          </label>
          <label class="select">
            <span>الترتيب</span>
            <select data-param="sort">
              ${[["featured", "مميز"], ["popular", "الأكثر طلباً"], ["new", "الأحدث"], ["price-asc", "السعر: من الأقل"], ["price-desc", "السعر: من الأعلى"], ["rating", "الأعلى تقييماً"]]
                .map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}
            </select>
          </label>
        </div>
      </div>
      ${grid(list)}
    </section>`;
  }

  function pageProduct(id) {
    const p = byId(id);
    if (!p) return pageNotFound();
    const related = PRODUCTS.filter((x) => x.category === p.category && x.id !== p.id)
      .concat(PRODUCTS.filter((x) => x.category !== p.category))
      .slice(0, 4);
    return `
    <section class="container product">
      <nav class="crumbs"><a href="#/">الرئيسية</a> / <a href="#/shop?cat=${p.category}">${catName(p.category)}</a> / <span>${esc(p.name)}</span></nav>
      <div class="product__grid">
        <div class="product__gallery">
          <div class="product__img" id="zoom">
            <img src="${p.image}" alt="${esc(p.name)}" width="600" height="750" />
            ${badgeHTML(p)}
          </div>
        </div>
        <div class="product__info">
          <span class="card__cat">${catName(p.category)}</span>
          <h1>${esc(p.name)}</h1>
          <div class="card__meta">${stars(p.rating)} <small>${p.rating} · ${p.reviews} تقييم</small></div>
          <div class="price price--lg">
            <strong>${money(p.price)}</strong>
            ${p.oldPrice ? `<del>${money(p.oldPrice)}</del><span class="save">وفّري ${money(p.oldPrice - p.price)}</span>` : ""}
          </div>
          <p class="product__desc">${esc(p.description)}</p>
          <div class="opt"><span>اللون:</span> <strong>${esc(p.color)}</strong></div>
          <div class="opt">
            <span>المقاس:</span> <a href="#/page/sizes" class="link-sm">دليل المقاسات</a>
            <div class="sizes" id="sizes">
              ${p.sizes.map((s, i) => `<button class="size ${i === 1 || p.sizes.length === 1 ? "on" : ""}" data-size="${s}">${s}</button>`).join("")}
            </div>
          </div>
          <div class="buy">
            <div class="qty" id="qty">
              <button data-q="1" aria-label="زيادة">+</button>
              <input type="number" value="1" min="1" max="20" aria-label="الكمية" />
              <button data-q="-1" aria-label="إنقاص">−</button>
            </div>
            <button class="btn btn--gold btn--lg grow" id="addBtn">أضيفي إلى السلة</button>
            <button class="wish wish--lg ${wish.includes(p.id) ? "on" : ""}" data-wish="${p.id}" aria-label="المفضلة">
              <svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-9.2-9A5 5 0 0 1 12 6a5 5 0 0 1 9.2 5C19 15.6 12 20 12 20z"/></svg>
            </button>
          </div>
          <button class="btn btn--dark btn--lg btn--block" id="buyNow">اطلبي الآن — الدفع عند الاستلام</button>
          <ul class="product__features">
            ${p.features.map((f) => `<li>✦ ${esc(f)}</li>`).join("")}
          </ul>
          <div class="assure">
            <div>🚚 <span>توصيل خلال 24–72 ساعة</span></div>
            <div>💵 <span>ادفعي عند الاستلام</span></div>
            <div>🔄 <span>استبدال خلال 7 أيام</span></div>
          </div>
        </div>
      </div>
    </section>
    <section class="section container">
      ${sectionHead("قد يعجبكِ أيضاً", "You may also like")}
      ${grid(related)}
    </section>`;
  }

  function pageWishlist() {
    const list = wish.map(byId).filter(Boolean);
    return `
    <section class="page-hero"><div class="container">
      <nav class="crumbs"><a href="#/">الرئيسية</a> / <span>المفضلة</span></nav>
      <h1>المفضلة</h1><p>${list.length} منتج</p>
    </div></section>
    <section class="container shop">${
      list.length ? grid(list)
        : `<div class="empty"><p>قائمة المفضلة فارغة. اضغطي على ♥ لحفظ القطع التي تعجبك.</p><a class="btn btn--gold" href="#/shop">تصفحي المتجر</a></div>`
    }</section>`;
  }

  function shippingFor(wilayaId, type) {
    const w = C.wilayas.find((x) => x[0] === +wilayaId);
    if (!w) return null;
    if (C.freeShippingFrom && subtotal() >= C.freeShippingFrom) return 0;
    return C.shippingZones[w[2]][type === "desk" ? 1 : 0];
  }

  function pageCheckout() {
    const lines = cartLines();
    if (!lines.length) {
      return `<section class="container narrow"><div class="empty">
        <p>سلتك فارغة حالياً 🛍️</p><a class="btn btn--gold" href="#/shop">ابدئي التسوق</a></div></section>`;
    }
    return `
    <section class="page-hero"><div class="container">
      <nav class="crumbs"><a href="#/">الرئيسية</a> / <span>إتمام الطلب</span></nav>
      <h1>إتمام الطلب</h1><p>املئي معلوماتك وسنتصل بك لتأكيد الطلب. الدفع عند الاستلام.</p>
    </div></section>
    <section class="container checkout">
      <form class="form" id="checkoutForm" novalidate>
        <h2>معلومات التوصيل</h2>
        <div class="row">
          <label class="field"><span>الاسم الكامل *</span>
            <input name="name" required autocomplete="name" placeholder="مثال: سارة بن علي" /></label>
          <label class="field"><span>رقم الهاتف *</span>
            <input name="phone" required type="tel" inputmode="tel" autocomplete="tel" placeholder="05 / 06 / 07 XX XX XX XX" dir="ltr" /></label>
        </div>
        <div class="row">
          <label class="field"><span>الولاية *</span>
            <select name="wilaya" required>
              <option value="">اختاري الولاية</option>
              ${C.wilayas.map(([n, name]) => `<option value="${n}">${String(n).padStart(2, "0")} - ${name}</option>`).join("")}
            </select></label>
          <label class="field"><span>البلدية *</span>
            <input name="commune" required placeholder="اسم البلدية" /></label>
        </div>
        <label class="field"><span>العنوان</span>
          <input name="address" autocomplete="street-address" placeholder="الحي، الشارع، رقم المنزل (اختياري للتوصيل للمكتب)" /></label>
        <fieldset class="delivery">
          <legend>طريقة التوصيل</legend>
          <label class="radio"><input type="radio" name="delivery" value="home" checked />
            <span><strong>🏠 التوصيل للمنزل</strong><small id="homePrice">اختاري الولاية</small></span></label>
          <label class="radio"><input type="radio" name="delivery" value="desk" />
            <span><strong>🏢 التوصيل للمكتب</strong><small id="deskPrice">اختاري الولاية</small></span></label>
        </fieldset>
        <label class="field"><span>ملاحظات</span>
          <textarea name="notes" rows="3" placeholder="أي ملاحظة حول الطلب (اختياري)"></textarea></label>
        <p class="form__err" id="formErr" role="alert"></p>
        <button class="btn btn--gold btn--lg btn--block" type="submit" id="submitOrder">تأكيد الطلب</button>
        <p class="muted center">بالضغط على «تأكيد الطلب» سيتم إرسال طلبك وفتح واتساب لتأكيده بسرعة.</p>
      </form>

      <aside class="summary">
        <h2>ملخص الطلب</h2>
        <ul class="summary__list">
          ${lines.map((l) => `
            <li>
              <img src="${l.product.image}" alt="" />
              <div><strong>${esc(l.product.name)}</strong><small>المقاس: ${esc(l.size)} · الكمية: ${l.qty}</small></div>
              <span>${money(l.product.price * l.qty)}</span>
            </li>`).join("")}
        </ul>
        <div class="totals">
          <div><span>المجموع الفرعي</span><span>${money(subtotal())}</span></div>
          <div><span>التوصيل</span><span id="shipCost">—</span></div>
          <div class="grand"><span>الإجمالي</span><span id="grandTotal">${money(subtotal())}</span></div>
        </div>
        ${freeShipBar()}
      </aside>
    </section>`;
  }

  function pageSuccess(orderId) {
    const order = store.get("orders", []).find((o) => o.id === orderId);
    if (!order) return pageNotFound();
    return `
    <section class="container narrow success">
      <div class="success__icon">✓</div>
      <h1>شكراً لكِ ${esc(order.customer.name)}! 💗</h1>
      <p>تم استلام طلبك رقم <strong dir="ltr">${order.id}</strong>. سنتصل بك على الرقم <strong dir="ltr">${esc(order.customer.phone)}</strong> لتأكيد الطلب قريباً.</p>
      <div class="success__box">
        <div><span>الإجمالي</span><strong>${money(order.total)}</strong></div>
        <div><span>التوصيل إلى</span><strong>${esc(order.customer.wilayaName)} — ${esc(order.customer.commune)}</strong></div>
        <div><span>الدفع</span><strong>عند الاستلام</strong></div>
      </div>
      <p class="muted">لم يُفتح واتساب؟ أرسلي الطلب يدوياً لتسريع التأكيد:</p>
      <div class="hero__cta center">
        <a class="btn btn--gold" href="${waLink(orderMessage(order))}" target="_blank" rel="noopener">إرسال الطلب عبر واتساب</a>
        <a class="btn btn--ghost" href="#/shop">مواصلة التسوق</a>
      </div>
    </section>`;
  }

  function pageTrack() {
    const orders = store.get("orders", []).slice().reverse();
    return `
    <section class="page-hero"><div class="container">
      <nav class="crumbs"><a href="#/">الرئيسية</a> / <span>طلباتي</span></nav>
      <h1>طلباتي</h1><p>الطلبات التي أرسلتِها من هذا الجهاز</p>
    </div></section>
    <section class="container narrow">
      ${orders.length ? `<div class="orders">${orders.map((o) => `
        <div class="order">
          <div><strong dir="ltr">${o.id}</strong><small>${new Date(o.date).toLocaleDateString("ar-DZ", { dateStyle: "long" })}</small></div>
          <div><small>${o.items.reduce((s, i) => s + i.qty, 0)} قطع</small><strong>${money(o.total)}</strong></div>
          <span class="status">قيد التأكيد</span>
          <a class="btn btn--ghost btn--sm" href="${waLink(`مرحباً، أريد الاستفسار عن طلبي رقم ${o.id}`)}" target="_blank" rel="noopener">استفسار</a>
        </div>`).join("")}</div>`
        : `<div class="empty"><p>لا توجد طلبات بعد.</p><a class="btn btn--gold" href="#/shop">تسوّقي الآن</a></div>`}
      <p class="muted center">للاستفسار عن أي طلب تواصلي معنا عبر واتساب: <a href="${waLink("مرحباً Victoria 👋")}" target="_blank" rel="noopener" dir="ltr">${esc(C.phone)}</a></p>
    </section>`;
  }

  const PAGES = {
    shipping: ["التوصيل والدفع", `
      <p>نوصل طلباتك إلى <strong>كل الولايات</strong> عبر شركات توصيل موثوقة، إلى المنزل أو إلى مكتب شركة التوصيل.</p>
      <ul>
        <li>مدة التوصيل: من 24 إلى 72 ساعة حسب الولاية.</li>
        <li>الدفع نقداً <strong>عند الاستلام</strong> — لا حاجة لأي دفع مسبق.</li>
        <li>يمكنك معاينة الطرد قبل الدفع.</li>
        <li>التوصيل مجاني للطلبات التي تفوق ${money(C.freeShippingFrom)}.</li>
      </ul>
      <h3>أسعار التوصيل</h3>
      <table class="table"><thead><tr><th>المنطقة</th><th>للمنزل</th><th>للمكتب</th></tr></thead><tbody>
      ${Object.entries(C.shippingZones).map(([z, [h, d]]) => `<tr><td>${["", "الوسط", "الشمال والهضاب", "الجنوب", "الجنوب الكبير"][z] || z}</td><td>${money(h)}</td><td>${money(d)}</td></tr>`).join("")}
      </tbody></table>`],
    returns: ["الاستبدال والإرجاع", `
      <p>رضاكِ يهمنا! يمكنك استبدال المنتج خلال <strong>7 أيام</strong> من تاريخ الاستلام بشرط:</p>
      <ul>
        <li>أن يكون المنتج بحالته الأصلية، غير مستعمل وغير مغسول.</li>
        <li>أن يكون في تغليفه الأصلي مع الملصقات.</li>
        <li>تكاليف التوصيل في حالة الاستبدال يتحملها الزبون إلا إذا كان الخطأ منا.</li>
      </ul>
      <p>للاستبدال تواصلي معنا عبر واتساب مع رقم الطلب.</p>`],
    sizes: ["دليل المقاسات", `
      <p>القياسات بالسنتيمتر. إذا كنتِ بين مقاسين ننصح بالمقاس الأكبر لراحة أكثر.</p>
      <table class="table"><thead><tr><th>المقاس</th><th>الصدر</th><th>الخصر</th><th>الأرداف</th></tr></thead><tbody>
        <tr><td>S</td><td>84–88</td><td>64–68</td><td>90–94</td></tr>
        <tr><td>M</td><td>88–94</td><td>68–74</td><td>94–100</td></tr>
        <tr><td>L</td><td>94–100</td><td>74–80</td><td>100–106</td></tr>
        <tr><td>XL</td><td>100–108</td><td>80–88</td><td>106–114</td></tr>
        <tr><td>XXL</td><td>108–116</td><td>88–96</td><td>114–122</td></tr>
      </tbody></table>`],
  };

  function pageStatic(key) {
    const pg = PAGES[key];
    if (!pg) return pageNotFound();
    return `
    <section class="page-hero"><div class="container">
      <nav class="crumbs"><a href="#/">الرئيسية</a> / <span>${pg[0]}</span></nav><h1>${pg[0]}</h1>
    </div></section>
    <section class="container narrow prose">${pg[1]}</section>`;
  }

  const pageNotFound = () => `
    <section class="container narrow"><div class="empty">
      <h1 class="gold">404</h1><p>الصفحة غير موجودة.</p><a class="btn btn--gold" href="#/">العودة للرئيسية</a>
    </div></section>`;

  /* ---------------- cart drawer ---------------- */
  function freeShipBar() {
    if (!C.freeShippingFrom) return "";
    const s = subtotal();
    const pct = Math.min(100, (s / C.freeShippingFrom) * 100);
    const msg = s >= C.freeShippingFrom
      ? "🎉 مبروك! حصلتِ على التوصيل المجاني"
      : `أضيفي ${money(C.freeShippingFrom - s)} للحصول على توصيل مجاني`;
    return `<div class="freeship"><small>${msg}</small><div class="bar"><span style="width:${pct}%"></span></div></div>`;
  }

  function renderCartUI() {
    updateBadges();
    const lines = cartLines();
    const body = $("#cartBody");
    const foot = $("#cartFoot");
    if (!lines.length) {
      body.innerHTML = `<div class="empty empty--sm"><p>سلتك فارغة 🛍️</p><a class="btn btn--gold" href="#/shop" data-close>تسوّقي الآن</a></div>`;
      foot.innerHTML = "";
      return;
    }
    body.innerHTML = freeShipBar() + lines.map((l, i) => `
      <div class="line">
        <img src="${l.product.image}" alt="" />
        <div class="line__info">
          <a href="#/product/${l.id}" data-close><strong>${esc(l.product.name)}</strong></a>
          <small>المقاس: ${esc(l.size)}</small>
          <div class="qty qty--sm">
            <button data-line="${i}" data-d="1" aria-label="زيادة">+</button>
            <span>${l.qty}</span>
            <button data-line="${i}" data-d="-1" aria-label="إنقاص">−</button>
          </div>
        </div>
        <div class="line__end">
          <strong>${money(l.product.price * l.qty)}</strong>
          <button class="link-sm" data-remove="${i}">حذف</button>
        </div>
      </div>`).join("");
    foot.innerHTML = `
      <div class="totals"><div class="grand"><span>المجموع</span><span>${money(subtotal())}</span></div></div>
      <a class="btn btn--gold btn--lg btn--block" href="#/checkout" data-close>إتمام الطلب</a>
      <button class="btn btn--ghost btn--block" data-close>مواصلة التسوق</button>`;
  }

  function updateBadges() {
    const cc = $("#cartCount"), wc = $("#wishCount");
    const n = cartQty();
    cc.textContent = n; cc.hidden = !n;
    wc.textContent = wish.length; wc.hidden = !wish.length;
  }

  const drawer = $("#cartDrawer"), overlay = $("#overlay");
  function openCart() {
    renderCartUI();
    drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
    overlay.hidden = false; requestAnimationFrame(() => overlay.classList.add("show"));
    document.body.classList.add("lock");
  }
  function closeAll() {
    drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true");
    $("#nav").classList.remove("open");
    overlay.classList.remove("show");
    setTimeout(() => { if (!overlay.classList.contains("show")) overlay.hidden = true; }, 300);
    document.body.classList.remove("lock");
  }

  /* ---------------- orders ---------------- */
  const waLink = (text) => `https://wa.me/${C.whatsapp}?text=${encodeURIComponent(text)}`;

  function orderMessage(o) {
    const lines = o.items.map((i) => `• ${i.name} | المقاس ${i.size} | ×${i.qty} = ${money(i.price * i.qty)}`).join("\n");
    return [
      `🛍️ طلب جديد من متجر Victoria`,
      `رقم الطلب: ${o.id}`,
      ``,
      lines,
      ``,
      `المجموع الفرعي: ${money(o.subtotal)}`,
      `التوصيل (${o.customer.delivery === "desk" ? "للمكتب" : "للمنزل"}): ${o.shipping ? money(o.shipping) : "مجاني"}`,
      `الإجمالي: ${money(o.total)}`,
      ``,
      `👤 الاسم: ${o.customer.name}`,
      `📞 الهاتف: ${o.customer.phone}`,
      `📍 الولاية: ${o.customer.wilayaName} — ${o.customer.commune}`,
      o.customer.address ? `🏠 العنوان: ${o.customer.address}` : "",
      o.customer.notes ? `📝 ملاحظات: ${o.customer.notes}` : "",
    ].filter((x, i, a) => x !== "" || a[i - 1] !== "").join("\n");
  }

  const normalizePhone = (v) => v.replace(/[\s.\-()]/g, "").replace(/^\+213|^00213/, "0");
  const validPhone = (v) => /^0[567]\d{8}$/.test(normalizePhone(v));

  function bindCheckout() {
    const form = $("#checkoutForm");
    if (!form) return;
    const update = () => {
      const wil = form.wilaya.value;
      const type = form.delivery.value;
      const home = shippingFor(wil, "home"), desk = shippingFor(wil, "desk");
      $("#homePrice").textContent = home == null ? "اختاري الولاية" : home ? money(home) : "مجاني";
      $("#deskPrice").textContent = desk == null ? "اختاري الولاية" : desk ? money(desk) : "مجاني";
      const ship = shippingFor(wil, type);
      $("#shipCost").textContent = ship == null ? "—" : ship ? money(ship) : "مجاني";
      $("#grandTotal").textContent = money(subtotal() + (ship || 0));
    };
    form.addEventListener("change", update);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $("#formErr");
      const d = Object.fromEntries(new FormData(form));
      $$(".field", form).forEach((f) => f.classList.remove("invalid"));
      const bad = [];
      if (d.name.trim().length < 3) bad.push("name");
      if (!validPhone(d.phone)) bad.push("phone");
      if (!d.wilaya) bad.push("wilaya");
      if (d.commune.trim().length < 2) bad.push("commune");
      if (d.delivery === "home" && d.address.trim().length < 4) bad.push("address");
      if (bad.length) {
        bad.forEach((n) => form[n].closest(".field").classList.add("invalid"));
        err.textContent = bad.includes("phone")
          ? "يرجى إدخال رقم هاتف صحيح (10 أرقام يبدأ بـ 05 أو 06 أو 07)."
          : bad.includes("address") && bad.length === 1
            ? "يرجى إدخال العنوان للتوصيل إلى المنزل."
            : "يرجى ملء جميع الحقول المطلوبة.";
        form[bad[0]].focus();
        return;
      }
      err.textContent = "";
      const btn = $("#submitOrder");
      btn.disabled = true; btn.textContent = "جارٍ الإرسال...";

      const shipping = shippingFor(d.wilaya, d.delivery) || 0;
      const order = {
        id: "VIC-" + Date.now().toString(36).toUpperCase().slice(-6),
        date: new Date().toISOString(),
        items: cartLines().map((l) => ({ id: l.id, name: l.product.name, size: l.size, qty: l.qty, price: l.product.price })),
        subtotal: subtotal(),
        shipping,
        total: subtotal() + shipping,
        customer: {
          name: d.name.trim(), phone: normalizePhone(d.phone),
          wilaya: +d.wilaya, wilayaName: C.wilayas.find((w) => w[0] === +d.wilaya)[1],
          commune: d.commune.trim(), address: d.address.trim(), delivery: d.delivery, notes: d.notes.trim(),
        },
      };

      // Open WhatsApp synchronously (inside the click) so popup blockers allow it.
      const wa = window.open(waLink(orderMessage(order)), "_blank");
      if (wa) wa.opener = null;

      if (C.orderEndpoint) {
        try {
          await fetch(C.orderEndpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(order),
          });
        } catch { /* WhatsApp copy still reaches the store */ }
      }

      const orders = store.get("orders", []);
      orders.push(order);
      store.set("orders", orders);
      cart = [];
      saveCart();
      if (!wa) toast("اضغطي «إرسال الطلب عبر واتساب» لتأكيد طلبك");
      location.hash = `#/success/${order.id}`;
    });
  }

  function bindProduct(id) {
    const p = byId(id);
    if (!p || !$("#addBtn")) return;
    const qtyInput = $("#qty input");
    const getSize = () => ($(".size.on") || {}).dataset?.size;
    const getQty = () => Math.max(1, Math.min(20, parseInt(qtyInput.value, 10) || 1));
    $("#sizes").addEventListener("click", (e) => {
      const b = e.target.closest(".size");
      if (!b) return;
      $$(".size").forEach((x) => x.classList.toggle("on", x === b));
    });
    $("#qty").addEventListener("click", (e) => {
      const b = e.target.closest("[data-q]");
      if (!b) return;
      qtyInput.value = Math.max(1, Math.min(20, getQty() + +b.dataset.q));
    });
    const need = () => { if (!getSize()) { toast("يرجى اختيار المقاس"); return false; } return true; };
    $("#addBtn").addEventListener("click", () => { if (need()) addToCart(p.id, getSize(), getQty()); });
    $("#buyNow").addEventListener("click", () => {
      if (!need()) return;
      addToCart(p.id, getSize(), getQty());
      location.hash = "#/checkout";
    });
    const z = $("#zoom"), img = $("#zoom img");
    z.addEventListener("mousemove", (e) => {
      const r = z.getBoundingClientRect();
      img.style.transformOrigin = `${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`;
      img.style.transform = "scale(1.6)";
    });
    z.addEventListener("mouseleave", () => { img.style.transform = ""; });
  }

  /* ---------------- router ---------------- */
  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, qs] = raw.split("?");
    return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(qs || "") };
  }

  const TITLES = { shop: "المتجر", checkout: "إتمام الطلب", wishlist: "المفضلة", track: "طلباتي" };

  function route() {
    const { parts, params } = parseHash();
    const [r, arg] = parts;
    let html;
    switch (r) {
      case undefined: html = pageHome(); break;
      case "shop": html = pageShop(params); break;
      case "product": html = pageProduct(arg); break;
      case "checkout": html = pageCheckout(); break;
      case "wishlist": html = pageWishlist(); break;
      case "success": html = pageSuccess(arg); break;
      case "track": html = pageTrack(); break;
      case "page": html = pageStatic(arg); break;
      default: html = pageNotFound();
    }
    app.innerHTML = html;

    const prod = r === "product" && byId(arg);
    document.title = `${prod ? prod.name : TITLES[r] || (PAGES[arg] || [])[0] || "بيجامات وملابس منزلية فاخرة"} | Victoria`;

    const key = r === "shop" && params.get("cat") ? params.get("cat") : r || "home";
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.link === key));

    if (r === "product") bindProduct(arg);
    if (r === "checkout") bindCheckout();
    closeAll();
    window.scrollTo(0, 0);
    observeReveal();
  }

  /* ---------------- reveal on scroll ---------------- */
  let io;
  function observeReveal() {
    const els = $$(".reveal:not(.in)");
    if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      els.forEach((el) => el.classList.add("in"));
      return;
    }
    io = io || new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    }), { rootMargin: "0px 0px -40px 0px" });
    els.forEach((el) => io.observe(el));
  }

  /* ---------------- global events ---------------- */
  document.addEventListener("click", (e) => {
    const t = e.target;
    const quick = t.closest("[data-quick]");
    if (quick) {
      const p = byId(quick.dataset.quick);
      addToCart(p.id, p.sizes[Math.min(1, p.sizes.length - 1)]);
      return;
    }
    const w = t.closest("[data-wish]");
    if (w) { toggleWish(w.dataset.wish); return; }
    const line = t.closest("[data-line]");
    if (line) {
      const l = cart[+line.dataset.line];
      l.qty = Math.max(1, Math.min(20, l.qty + +line.dataset.d));
      saveCart(); return;
    }
    const rm = t.closest("[data-remove]");
    if (rm) { cart.splice(+rm.dataset.remove, 1); saveCart(); return; }
    if (t.closest("[data-close]")) {
      closeAll();
      // a link to the current hash would not trigger hashchange
      const a = t.closest("a[href^='#']");
      if (a && a.getAttribute("href") === location.hash) route();
    }
  });

  app.addEventListener("change", (e) => {
    const s = e.target.closest("select[data-param]");
    if (!s) return;
    const { params } = parseHash();
    s.value ? params.set(s.dataset.param, s.value) : params.delete(s.dataset.param);
    location.hash = "#/shop" + (params.toString() ? "?" + params : "");
  });

  $("#cartBtn").addEventListener("click", openCart);
  $("#cartClose").addEventListener("click", closeAll);
  overlay.addEventListener("click", closeAll);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

  $("#menuBtn").addEventListener("click", () => {
    $("#nav").classList.add("open");
    overlay.hidden = false; requestAnimationFrame(() => overlay.classList.add("show"));
  });

  $("#searchBtn").addEventListener("click", () => {
    const sb = $("#searchbar");
    sb.hidden = !sb.hidden;
    if (!sb.hidden) $("#searchInput").focus();
  });
  $("#searchbar").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#searchInput").value.trim();
    $("#searchbar").hidden = true;
    location.hash = "#/shop" + (q ? "?q=" + encodeURIComponent(q) : "");
  });

  window.addEventListener("scroll", () => $("#header").classList.toggle("scrolled", scrollY > 10), { passive: true });
  window.addEventListener("hashchange", route);
  window.addEventListener("storage", (e) => {
    if (e.key === "victoria:cart") { cart = store.get("cart", []); renderCartUI(); }
    if (e.key === "victoria:wish") { wish = store.get("wish", []); updateBadges(); }
  });

  /* ---------------- static bits ---------------- */
  const msgs = [
    "🚚 توصيل لكل الولايات — الدفع عند الاستلام",
    C.freeShippingFrom ? `✨ توصيل مجاني للطلبات فوق ${money(C.freeShippingFrom)}` : "",
    "🎁 تغليف هدية أنيق مع كل طلب",
  ].filter(Boolean);
  $("#announce").innerHTML = `<div class="announce__track">${[...msgs, ...msgs].map((m) => `<span>${m}</span>`).join("")}</div>`;
  $("#year").textContent = new Date().getFullYear();
  $("#waFloat").href = waLink("مرحباً Victoria 👋 أريد الاستفسار عن منتجاتكم");
  $("#footerContact").innerHTML = `
    <li><a href="${waLink("مرحباً Victoria 👋")}" target="_blank" rel="noopener">📱 <span dir="ltr">${esc(C.phone)}</span></a></li>
    <li><a href="mailto:${esc(C.email)}">✉️ ${esc(C.email)}</a></li>`;
  $("#socials").innerHTML = [["Instagram", C.instagram, "IG"], ["Facebook", C.facebook, "FB"], ["TikTok", C.tiktok, "TT"]]
    .filter(([, u]) => u)
    .map(([n, u, s]) => `<a href="${u}" target="_blank" rel="noopener" aria-label="${n}">${s}</a>`).join("");

  renderCartUI();
  route();
})();
