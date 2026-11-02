/* =========================================================
   كتالوج المنتجات — أضف أو عدّل منتجاتك هنا
   image: مسار الصورة (يمكن استبدالها بصور حقيقية .jpg / .webp)
   oldPrice: السعر قبل التخفيض (اختياري)
   badge: "new" | "best" | "sale" (اختياري)
   ========================================================= */
window.CATEGORIES = [
  { id: "pyjamas", name: "بيجامات", icon: "🌙" },
  { id: "shorts", name: "أطقم صيفية", icon: "☀️" },
  { id: "robes", name: "روبات", icon: "👘" },
  { id: "nightgowns", name: "قمصان نوم", icon: "🎀" },
];

window.PRODUCTS = [
  {
    id: "pink-classic", category: "pyjamas", badge: "best",
    name: "بيجامة ساتان وردية كلاسيكية", price: 4900, oldPrice: 5900,
    image: "assets/img/products/pink-classic.svg", rating: 4.9, reviews: 128,
    sizes: ["S", "M", "L", "XL", "XXL"], color: "وردي",
    description: "بيجامة من الساتان الناعم بلون وردي أنيق مع حواف سوداء متباينة، قميص بأزرار وجيب صدر وبنطال واسع مريح. مثالية لليالي الهادئة ولحظات الدلال.",
    features: ["ساتان ناعم لامع", "حواف مزخرفة (Piping)", "خصر مطاطي مريح", "قابلة للغسل في الغسالة"],
  },
  {
    id: "black-royal", category: "pyjamas", badge: "new",
    name: "بيجامة ساتان سوداء ملكية", price: 5200,
    image: "assets/img/products/black-royal.svg", rating: 4.8, reviews: 76,
    sizes: ["S", "M", "L", "XL", "XXL"], color: "أسود وذهبي",
    description: "فخامة اللون الأسود مع لمسات ذهبية راقية. بيجامة ساتان بقصة كلاسيكية تمنحك إطلالة ملكية حتى في المنزل.",
    features: ["ساتان فاخر", "حواف ذهبية", "قصة مريحة", "هدية مثالية"],
  },
  {
    id: "champagne", category: "pyjamas",
    name: "بيجامة ساتان شامبانيا", price: 5200,
    image: "assets/img/products/champagne.svg", rating: 4.7, reviews: 54,
    sizes: ["S", "M", "L", "XL"], color: "شامبانيا",
    description: "لون الشامبانيا الدافئ مع لمعة الساتان الحريرية، تصميم ناعم يجمع بين الأناقة والراحة.",
    features: ["ملمس حريري", "قميص بأزرار", "بنطال واسع", "خفيفة الوزن"],
  },
  {
    id: "navy-night", category: "pyjamas", badge: "sale",
    name: "بيجامة كحلية ليلية", price: 4500, oldPrice: 5600,
    image: "assets/img/products/navy-night.svg", rating: 4.6, reviews: 41,
    sizes: ["M", "L", "XL", "XXL"], color: "كحلي",
    description: "بيجامة بلون كحلي عميق مع حواف ذهبية فاتحة، تناسب الأمسيات الشتوية بأناقة هادئة.",
    features: ["ساتان سميك", "حواف ذهبية", "جيب صدر", "مقاسات كبيرة متوفرة"],
  },
  {
    id: "sky-dream", category: "pyjamas",
    name: "بيجامة سماوية حالمة", price: 4900,
    image: "assets/img/products/sky-dream.svg", rating: 4.8, reviews: 33,
    sizes: ["S", "M", "L", "XL"], color: "أزرق سماوي",
    description: "لون سماوي هادئ يبعث على الاسترخاء مع حواف بيضاء ناعمة. لأحلام أجمل.",
    features: ["ساتان ناعم", "حواف بيضاء", "قصة كلاسيكية", "مريحة للنوم"],
  },
  {
    id: "lilac-short", category: "shorts", badge: "new",
    name: "طقم شورت ساتان ليلكي", price: 3900,
    image: "assets/img/products/lilac-short.svg", rating: 4.9, reviews: 62,
    sizes: ["S", "M", "L", "XL"], color: "ليلكي",
    description: "طقم صيفي خفيف: قميص بأكمام طويلة وشورت قصير بلون ليلكي ناعم، مثالي للأيام الدافئة.",
    features: ["خفيف ومنعش", "شورت بخصر مطاطي", "حواف بنفسجية", "مثالي للصيف"],
  },
  {
    id: "mint-short", category: "shorts",
    name: "طقم شورت ساتان نعناعي", price: 3900,
    image: "assets/img/products/mint-short.svg", rating: 4.7, reviews: 29,
    sizes: ["S", "M", "L", "XL"], color: "أخضر نعناعي",
    description: "انتعاش اللون النعناعي مع نعومة الساتان. طقم شورت مريح لليالي الصيف.",
    features: ["ساتان خفيف", "ألوان منعشة", "قصة مريحة", "سهل العناية"],
  },
  {
    id: "burgundy-robe", category: "robes", badge: "best",
    name: "روب ساتان طويل عنابي", price: 6500,
    image: "assets/img/products/burgundy-robe.svg", rating: 5.0, reviews: 88,
    sizes: ["S/M", "L/XL", "XXL"], color: "عنابي",
    description: "روب طويل فاخر بلون عنابي ملكي مع ياقة وحزام بلون ذهبي. لمسة من الفخامة لصباحاتك.",
    features: ["طول كامل", "حزام قابل للربط", "ياقة متباينة", "أكمام واسعة"],
  },
  {
    id: "blush-robe", category: "robes",
    name: "روب كيمونو وردي ناعم", price: 6200,
    image: "assets/img/products/blush-robe.svg", rating: 4.8, reviews: 47,
    sizes: ["S/M", "L/XL", "XXL"], color: "وردي فاتح",
    description: "روب كيمونو بلون وردي فاتح مع ياقة وردية داكنة، أنوثة ورقة في كل تفصيلة.",
    features: ["قصة كيمونو", "حزام", "ساتان لامع", "مثالي للعروس"],
  },
  {
    id: "ivory-gown", category: "nightgowns", badge: "new",
    name: "قميص نوم حريري عاجي", price: 4500,
    image: "assets/img/products/ivory-gown.svg", rating: 4.9, reviews: 51,
    sizes: ["S", "M", "L", "XL"], color: "عاجي",
    description: "قميص نوم طويل بلون عاجي مع حمالات رفيعة وفيونكة ذهبية وحافة دانتيل. رقة لا تقاوم.",
    features: ["حمالات قابلة للتعديل", "حافة دانتيل", "فيونكة مزخرفة", "قماش انسيابي"],
  },
  {
    id: "black-lace-gown", category: "nightgowns", badge: "sale",
    name: "قميص نوم أسود بالدانتيل", price: 4200, oldPrice: 4800,
    image: "assets/img/products/black-lace-gown.svg", rating: 4.8, reviews: 69,
    sizes: ["S", "M", "L", "XL"], color: "أسود",
    description: "قميص نوم أسود أنيق مع تفاصيل وردية ودانتيل عند الحافة. جاذبية راقية.",
    features: ["دانتيل ناعم", "قصة انسيابية", "حمالات رفيعة", "تفاصيل وردية"],
  },
  {
    id: "rosegold-gown", category: "nightgowns",
    name: "قميص نوم روز جولد", price: 4800,
    image: "assets/img/products/rosegold-gown.svg", rating: 4.7, reviews: 22,
    sizes: ["S", "M", "L", "XL"], color: "روز جولد",
    description: "لون الروز جولد الساحر مع لمعة الساتان. قطعة تجمع الأنوثة والفخامة.",
    features: ["ساتان لامع", "حافة دانتيل", "فيونكة", "قصة طويلة"],
  },
];
