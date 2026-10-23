export type EntityType = 'Stock' | 'Commodity' | 'Macro' | 'News' | 'Sector';

export type ImpactType = 'POSITIVE' | 'NEGATIVE' | 'MIXED' | 'NEUTRAL';

export type GraphMode = 'constellation' | 'cluster' | 'linear';

export interface GraphEdge {
  id: string;
  label: 'EXPOSED_TO' | 'SENSITIVE_TO_MACRO' | 'DIRECTLY_IMPACTS' | 'INDIRECTLY_IMPACTS' | 'RELATED_TO' | 'IMPACTS_SECTOR';
  type: EntityType;
  confidence: number;
  impact: ImpactType;
  note: string;
  marginImpactPct?: string;
  rationale?: string;
  vendor?: string;
  timeAgo?: string;
  imageUrl?: string;
}

export interface GraphEntity {
  id: string;
  title: string;
  type: EntityType;
  sector: string;
  exchange: string;
  avatar: string;
  color: string;
  edges: GraphEdge[];
  description?: string;
  detailedCards?: DetailedCard[];
}

export interface DetailedCard {
  id: string;
  typeBadge: string;
  tag: string;
  badgeHalo: 'halo-orange' | 'halo-purple' | 'halo-emerald';
  relationLabel: string;
  confidence: number;
  timeAgo: string;
  source: string;
  headline: string;
  causalRationale: string;
  vendorOrMeta: string;
  marginBadgeText?: string;
  statVisual?: {
    primaryText: string;
    subText: string;
    secondaryText?: string;
  };
}

