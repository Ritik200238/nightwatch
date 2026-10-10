/**
 * What the exit cost is and is not, said wherever it is shown.
 *
 * Why: the cost is a walk of the resting orders visible on the Bitget book at one moment,
 * plus the taker fee. No study compares it with real fills, so the page says so rather
 * than let a measured-looking number read as a validated one.
 */

export const EXIT_COST_CAVEAT_SHORT = {
  en: "visible orders only, not checked against real fills",
  zh: "仅按可见挂单估算，未与真实成交核对",
} as const;

export const EXIT_COST_CAVEAT = {
  en: "An estimate: the resting orders visible on the Bitget book at that moment, walked for your size, plus the taker fee. It has not been checked against real fills. Other traders, and the book changing before you exit, can make the actual cost higher or lower.",
  zh: "这是估算：按当时 Bitget 盘口上可见的挂单，为你的仓位逐档计算，再加上吃单手续费。它尚未与真实成交核对。其他交易者，以及平仓前盘口的变化，都可能让实际成本更高或更低。",
} as const;
