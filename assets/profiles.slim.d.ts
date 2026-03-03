export const SPEC_VERSION = "2.0.0";
export interface ProfilesWrapper {
    spec: "flatprofiles";
    spec_version: string;
    data: ProfilesData;
    metadata?: Record<string, any>;
}
export interface ProfilesData {
    model_profiles: Record<string, ModelProfileConfig>;
    default?: string;
    override?: string;
}
export interface ModelProfileConfig {
    name: string;
    provider?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    top_k?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    seed?: number;
    base_url?: string;
    stream?: boolean;
}
export type FlatprofilesConfig = ProfilesWrapper;
