export interface BeastEntry {
  id: string
  name: string
  /** 图鉴卷轴上的短注 */
  epithet: string
  source: string
  ready: boolean
}

// 详细原文与设计推断放 content/beasts/*.json，这里只是图鉴索引
export const BEASTS: BeastEntry[] = [
  { id: 'jiuweihu', name: '九尾狐', epithet: '其状如狐而九尾', source: '南山经', ready: true },
  { id: 'bo', name: '驳', epithet: '其状如马，白身黑尾', source: '西山经', ready: false },
  { id: 'luwu', name: '陆吾', epithet: '虎身而九尾，人面', source: '西山经', ready: false },
  { id: 'bifang', name: '毕方', epithet: '其状如鹤，一足', source: '西山经', ready: false },
  { id: 'dijiang', name: '帝江', epithet: '浑敦无面目', source: '西山经', ready: true },
  { id: 'qiongqi', name: '穷奇', epithet: '其状如虎，有翼', source: '海内北经', ready: false },
  { id: 'taotie', name: '饕餮', epithet: '羊身人面，目在腋下', source: '北山经', ready: false },
  { id: 'kaiming', name: '开明兽', epithet: '身大类虎而九首', source: '海内西经', ready: false },
  { id: 'fenghuang', name: '凤凰', epithet: '其状如鸡，五采而文', source: '南山经', ready: false },
  { id: 'yinglong', name: '应龙', epithet: '应龙处南极', source: '大荒东经', ready: false },
]
