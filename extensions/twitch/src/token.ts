/**
 * Twitch access token resolution with environment variable support.
 *
 * Supports reading Twitch OAuth access tokens from config or environment variable.
 * The OPENCLAW_TWITCH_ACCESS_TOKEN env var is only used for the default account.
 *
 * Token resolution priority (default account):
 * 1. Environment variable: OPENCLAW_TWITCH_ACCESS_TOKEN (kept current by onRefresh callback)
 * 2. Account access token from merged config (base-level or accounts.default)
 *
 * For non-default accounts:
 * 1. Account access token from accounts.{accountId}
 */

import type { OpenClawConfig } from "../../../src/config/config.js";
import { DEFAULT_ACCOUNT_ID, normalizeAccountId } from "../../../src/routing/session-key.js";

export type TwitchTokenSource = "env" | "config" | "none";

export type TwitchTokenResolution = {
  token: string;
  source: TwitchTokenSource;
};

/**
 * Normalize a Twitch OAuth token - ensure it has the oauth: prefix
 */
function normalizeTwitchToken(raw?: string | null): string | undefined {
  if (!raw) {
    return undefined;
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return undefined;
  }
  // Twitch tokens should have oauth: prefix
  return trimmed.startsWith("oauth:") ? trimmed : `oauth:${trimmed}`;
}

/**
 * Resolve Twitch access token from config or environment variable.
 *
 * For the default account, process.env is checked FIRST because the onRefresh
 * callback updates process.env with fresh tokens after each Twitch token rotation.
 * The config object is expanded once at startup and becomes stale after a refresh.
 *
 * @param cfg - OpenClaw config
 * @param opts - Options including accountId and optional envToken override
 * @returns Token resolution with source
 */
export function resolveTwitchToken(
  cfg?: OpenClawConfig,
  opts: { accountId?: string | null; envToken?: string | null } = {},
): TwitchTokenResolution {
  const accountId = normalizeAccountId(opts.accountId);

  // For default account, check process.env FIRST — onRefresh keeps it current
  if (accountId === DEFAULT_ACCOUNT_ID) {
    const envToken = normalizeTwitchToken(
      opts.envToken ?? process.env.OPENCLAW_TWITCH_ACCESS_TOKEN,
    );
    if (envToken) {
      return { token: envToken, source: "env" };
    }
  }

  // Get merged account config (handles both simplified and multi-account patterns)
  const twitchCfg = cfg?.channels?.twitch;
  const accountCfg =
    accountId === DEFAULT_ACCOUNT_ID
      ? (twitchCfg?.accounts?.[DEFAULT_ACCOUNT_ID] as Record<string, unknown> | undefined)
      : (twitchCfg?.accounts?.[accountId] as Record<string, unknown> | undefined);

  let token: string | undefined;
  if (accountId === DEFAULT_ACCOUNT_ID) {
    token = normalizeTwitchToken(
      (typeof twitchCfg?.accessToken === "string" ? twitchCfg.accessToken : undefined) ||
        (accountCfg?.accessToken as string | undefined),
    );
  } else {
    token = normalizeTwitchToken(accountCfg?.accessToken as string | undefined);
  }

  if (token) {
    return { token, source: "config" };
  }

  return { token: "", source: "none" };
}
