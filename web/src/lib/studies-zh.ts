/** Chinese titles and questions for the studies, keyed by the study's stable `key`. The
 *  server writes each study in English; the title and the question are fixed per study, so
 *  they are translated here. How a study was run, what came back and the statistics carry
 *  computed numbers and stay in the server's English, which the page says plainly. */

export const STUDY_ZH: Record<string, { title: string; question: string }> = {
  closer_is_not_tighter: {
    title: "越相似的历史时刻，之后的结果就越集中吗？",
    question: "如果检索像大家以为的那样有效，离查询最近的那一半匹配，之后的结果范围应该比远的那一半更窄。真是这样吗？",
  },
  weighting_does_not_help: {
    title: "越相似的历史时刻应该占更大权重吗？",
    question: "样本群一直算着按相似度加权的均值和第 5 百分位，但没有任何地方在用。应该用吗？",
  },
  distance_does_not_warn: {
    title: "“找不到相似时刻”是在预警更大的波动吗？",
    question: "当交易台找不到和现在很像的历史时刻时，之后的走势是否比平时更剧烈？如果是，开仓前就值得明说。",
  },
  pooling_beats_own_history: {
    title: "一只代币最好只用它自己的历史来解释吗？",
    question: "代币化股票都是个股。检索应该只限于被问到的那一只，而不是在所有代币里找吗？",
  },
  one_factor_hid_two_errors: {
    title: "一个尾部系数适合所有持有期吗？",
    question: "样本群的第 5 百分位用一个按已到期预测拟合的系数来加宽。同一个系数对过夜和过周末的持有期同样合适吗？",
  },
  online_calibration_adds_nothing: {
    title: "在线校准更新会做得更好吗？",
    question: "自适应保形推断在每次结果出来后微调区间，而不是用全部历史重新拟合。它是针对区间漂移的公认修正方法，而漂移正是我们的症状。在这里有用吗？",
  },
  analogs_beat_random_hours: {
    title: "相似时刻比同类型的随机小时更准吗？",
    question: "每个预测还会存下一个由同一周内时段的随机历史小时组成的分布。如果检索什么作用都没有，两者的得分应该一样。它有作用吗？",
  },
  adjusted_analogs_beat_adjusted_baseline: {
    title: "两边都做同样的尾部修正后，相似时刻还比随机小时更准吗？",
    question: "我们发布的二十分之一线，是把相似时刻的尾部重新缩放到 5% 得到的。把随机小时的分布也做同样的缩放：如果它同样准、同样窄，说明检索什么都没贡献，全是缩放的功劳。",
  },
  narrowing_gives_a_truer_tail: {
    title: "收窄检索范围能得到更准的亏损尾部吗？",
    question: "当交易者只要“像今晚这样的夜晚”——财报夜、价差拉大、刚出新文件——返回的尾部往往比不筛选时差得多。它是更准了，还是只是更戏剧化了？",
  },
  disagreement_warns_of_a_breach: {
    title: "引擎自己和自己意见不一，是在预警亏损会越线吗？",
    question: "把检索换十几种略有不同的做法——邻居更少或更多、每次去掉一组特征——第 5 百分位就会移动。移动的幅度值得作为警告展示吗？各版本的平均值比我们发布的那个更准吗？",
  },
  filing_read_predicts_size: {
    title: "模型能识别出重要的文件吗？",
    question: "模型读每一份文件，并判断它撼动股价的可能性。被它判为高影响的，之后真的波动更大吗？",
  },
  filing_read_calls_direction: {
    title: "模型能判断方向吗？",
    question: "在文件重要程度之外，模型还会说它指向哪个方向。这是有对错之分的预测，所以可以打分。在它敢下“涨”或“跌”结论的文件上，它比抛硬币更常说对吗？",
  },
};
