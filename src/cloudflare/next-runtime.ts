import { getCloudflareContext } from "@opennextjs/cloudflare";

export type CTraderRuntimeEnv = {
  CTRADER_DB?: any;
  CTRADER_CLIENT_ID?: string;
  CTRADER_CLIENT_SECRET?: string;
  CTRADER_REDIRECT_URI?: string;
  CTRADER_TOKEN_ENCRYPTION_KEY?: string;
};

export function getCTraderRuntimeEnv(): CTraderRuntimeEnv {
  return getCloudflareContext().env as unknown as CTraderRuntimeEnv;
}
