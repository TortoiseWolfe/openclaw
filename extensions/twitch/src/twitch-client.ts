import { RefreshingAuthProvider, StaticAuthProvider } from "@twurple/auth";
import { ChatClient, LogLevel } from "@twurple/chat";
import type { OpenClawConfig } from "openclaw/plugin-sdk";
import { updateDotEnvFile, resolveGlobalDotEnvPath } from "../../../src/infra/dotenv-write.js";
import { DEFAULT_ACCOUNT_ID } from "./config.js";
import { resolveTwitchToken } from "./token.js";
import type { ChannelLogSink, TwitchAccountConfig, TwitchChatMessage } from "./types.js";
import { normalizeToken } from "./utils/twitch.js";

/**
 * Manages Twitch chat client connections
 */
export class TwitchClientManager {
  private clients = new Map<string, ChatClient>();
  private messageHandlers = new Map<string, (message: TwitchChatMessage) => void>();

  constructor(private logger: ChannelLogSink) {}

  /**
   * Create an auth provider for the account.
   */
  private async createAuthProvider(
    account: TwitchAccountConfig,
    normalizedToken: string,
    accountId?: string,
  ): Promise<StaticAuthProvider | RefreshingAuthProvider> {
    if (!account.clientId) {
      throw new Error("Missing Twitch client ID");
    }

    if (account.clientSecret) {
      const authProvider = new RefreshingAuthProvider({
        clientId: account.clientId,
        clientSecret: account.clientSecret,
      });

      const userId = await authProvider.addUserForToken({
        accessToken: normalizedToken,
        refreshToken: account.refreshToken ?? null,
        expiresIn: account.expiresIn ?? null,
        obtainmentTimestamp: account.obtainmentTimestamp ?? Date.now(),
      }, ['chat']);
      this.logger.info(
        `Added user ${userId} to RefreshingAuthProvider for ${account.username}`,
      );

      authProvider.onRefresh(async (userId, token) => {
        this.logger.info(
          `Access token refreshed for user ${userId} (expires in ${token.expiresIn ? `${token.expiresIn}s` : "unknown"})`,
        );

        // Persist refreshed tokens to ~/.openclaw/.env so they survive restarts.
        // The config file uses ${VAR} references — we update the .env source.
        try {
          const isDefault = !accountId || accountId === DEFAULT_ACCOUNT_ID;

          if (!isDefault) {
            this.logger.warn(
              `Token refresh for non-default account "${accountId}" — env persistence not supported`,
            );
            return;
          }

          const envPath = resolveGlobalDotEnvPath();
          const updates: Array<{ key: string; value: string }> = [
            { key: "OPENCLAW_TWITCH_ACCESS_TOKEN", value: token.accessToken },
          ];
          if (token.refreshToken) {
            updates.push({ key: "OPENCLAW_TWITCH_REFRESH_TOKEN", value: token.refreshToken });
          }
          if (token.expiresIn != null) {
            updates.push({ key: "OPENCLAW_TWITCH_EXPIRES_IN", value: String(token.expiresIn) });
          }
          updates.push({
            key: "OPENCLAW_TWITCH_OBTAINMENT_TIMESTAMP",
            value: String(token.obtainmentTimestamp),
          });

          await updateDotEnvFile(envPath, updates);

          // Update process.env for immediate use without restart
          process.env.OPENCLAW_TWITCH_ACCESS_TOKEN = token.accessToken;
          if (token.refreshToken) {
            process.env.OPENCLAW_TWITCH_REFRESH_TOKEN = token.refreshToken;
          }
          if (token.expiresIn != null) {
            process.env.OPENCLAW_TWITCH_EXPIRES_IN = String(token.expiresIn);
          }
          process.env.OPENCLAW_TWITCH_OBTAINMENT_TIMESTAMP = String(token.obtainmentTimestamp);

          this.logger.info(`Persisted refreshed tokens to ${envPath} for user ${userId}`);
        } catch (err) {
          this.logger.error(
            `Failed to persist refreshed tokens: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      });

      authProvider.onRefreshFailure((userId, error) => {
        this.logger.error(
          `TWITCH TOKEN DEAD — refresh failed for user ${userId}: ${error.message}. ` +
            `Generate new tokens: https://twitchtokengenerator.com — then update ` +
            `OPENCLAW_TWITCH_ACCESS_TOKEN and OPENCLAW_TWITCH_REFRESH_TOKEN in ` +
            `~/.openclaw/.env and restart: docker compose up -d --force-recreate openclaw-gateway`,
        );
      });

      const refreshStatus = account.refreshToken
        ? "automatic token refresh enabled"
        : "token refresh disabled (no refresh token)";
      this.logger.info(`Using RefreshingAuthProvider for ${account.username} (${refreshStatus})`);

      // Proactively validate token at startup: if the access token is expired,
      // attempt a refresh immediately so we fail fast with a clear error instead
      // of letting the ChatClient retry forever with a dead token.
      const isExpired =
        account.expiresIn != null &&
        account.obtainmentTimestamp != null &&
        Date.now() > account.obtainmentTimestamp + account.expiresIn * 1000;

      if (isExpired) {
        this.logger.info(
          `Access token for ${account.username} is expired — attempting proactive refresh…`,
        );
        try {
          await authProvider.refreshAccessTokenForUser(userId);
          this.logger.info(`Proactive token refresh succeeded for ${account.username}`);
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          throw new Error(
            `Twitch refresh token is invalid for ${account.username}: ${msg}. ` +
              `Generate new tokens: https://twitchtokengenerator.com — then update ` +
              `OPENCLAW_TWITCH_ACCESS_TOKEN and OPENCLAW_TWITCH_REFRESH_TOKEN in ` +
              `~/.openclaw/.env and restart: docker compose up -d --force-recreate openclaw-gateway`,
          );
        }
      }

      return authProvider;
    }

    this.logger.info(`Using StaticAuthProvider for ${account.username} (no clientSecret provided)`);
    return new StaticAuthProvider(account.clientId, normalizedToken);
  }

  /**
   * Get or create a chat client for an account
   */
  async getClient(
    account: TwitchAccountConfig,
    cfg?: OpenClawConfig,
    accountId?: string,
  ): Promise<ChatClient> {
    const key = this.getAccountKey(account);

    const existing = this.clients.get(key);
    if (existing) {
      return existing;
    }

    const tokenResolution = resolveTwitchToken(cfg, {
      accountId,
    });

    if (!tokenResolution.token) {
      this.logger.error(
        `Missing Twitch token for account ${account.username} (set channels.twitch.accounts.${account.username}.token or OPENCLAW_TWITCH_ACCESS_TOKEN for default)`,
      );
      throw new Error("Missing Twitch token");
    }

    this.logger.debug?.(`Using ${tokenResolution.source} token source for ${account.username}`);

    if (!account.clientId) {
      this.logger.error(`Missing Twitch client ID for account ${account.username}`);
      throw new Error("Missing Twitch client ID");
    }

    const normalizedToken = normalizeToken(tokenResolution.token);

    const authProvider = await this.createAuthProvider(account, normalizedToken, accountId);

    const client = new ChatClient({
      authProvider,
      channels: [account.channel],
      rejoinChannelsOnReconnect: true,
      requestMembershipEvents: true,
      logger: {
        minLevel: LogLevel.WARNING,
        custom: {
          log: (level, message) => {
            switch (level) {
              case LogLevel.CRITICAL:
                this.logger.error(message);
                break;
              case LogLevel.ERROR:
                this.logger.error(message);
                break;
              case LogLevel.WARNING:
                this.logger.warn(message);
                break;
              case LogLevel.INFO:
                this.logger.info(message);
                break;
              case LogLevel.DEBUG:
                this.logger.debug?.(message);
                break;
              case LogLevel.TRACE:
                this.logger.debug?.(message);
                break;
            }
          },
        },
      },
    });

    this.setupClientHandlers(client, account);

    await client.connect();

    this.clients.set(key, client);
    this.logger.info(`Connected to Twitch as ${account.username}`);

    return client;
  }

  /**
   * Set up message and event handlers for a client
   */
  private setupClientHandlers(client: ChatClient, account: TwitchAccountConfig): void {
    const key = this.getAccountKey(account);

    // Handle disconnections
    client.onDisconnect((manually, reason) => {
      if (manually) {
        this.logger.info(`Twitch client ${key} disconnected (manual)`);
      } else {
        this.logger.warn(
          `Twitch client ${key} disconnected unexpectedly: ${reason ?? "unknown reason"}`,
        );
      }
    });

    // Handle incoming messages
    client.onMessage((channelName, _user, messageText, msg) => {
      const handler = this.messageHandlers.get(key);
      if (handler) {
        const normalizedChannel = channelName.startsWith("#") ? channelName.slice(1) : channelName;
        const from = `twitch:${msg.userInfo.userName}`;
        const preview = messageText.slice(0, 100).replace(/\n/g, "\\n");
        this.logger.debug?.(
          `twitch inbound: channel=${normalizedChannel} from=${from} len=${messageText.length} preview="${preview}"`,
        );

        handler({
          username: msg.userInfo.userName,
          displayName: msg.userInfo.displayName,
          userId: msg.userInfo.userId,
          message: messageText,
          channel: normalizedChannel,
          id: msg.id,
          timestamp: new Date(),
          isMod: msg.userInfo.isMod,
          isOwner: msg.userInfo.isBroadcaster,
          isVip: msg.userInfo.isVip,
          isSub: msg.userInfo.isSubscriber,
          chatType: "group",
        });
      }
    });

    this.logger.info(`Set up handlers for ${key}`);
  }

  /**
   * Set a message handler for an account
   * @returns A function that removes the handler when called
   */
  onMessage(
    account: TwitchAccountConfig,
    handler: (message: TwitchChatMessage) => void,
  ): () => void {
    const key = this.getAccountKey(account);
    this.messageHandlers.set(key, handler);
    return () => {
      this.messageHandlers.delete(key);
    };
  }

  /**
   * Disconnect a client
   */
  async disconnect(account: TwitchAccountConfig): Promise<void> {
    const key = this.getAccountKey(account);
    const client = this.clients.get(key);

    if (client) {
      client.quit();
      this.clients.delete(key);
      this.messageHandlers.delete(key);
      this.logger.info(`Disconnected ${key}`);
    }
  }

  /**
   * Disconnect all clients
   */
  async disconnectAll(): Promise<void> {
    this.clients.forEach((client) => client.quit());
    this.clients.clear();
    this.messageHandlers.clear();
    this.logger.info("Disconnected all clients");
  }

  /**
   * Send a message to a channel
   */
  async sendMessage(
    account: TwitchAccountConfig,
    channel: string,
    message: string,
    cfg?: OpenClawConfig,
    accountId?: string,
  ): Promise<{ ok: boolean; error?: string; messageId?: string }> {
    try {
      const client = await this.getClient(account, cfg, accountId);

      // Generate a message ID (Twurple's say() doesn't return the message ID, so we generate one)
      const messageId = crypto.randomUUID();

      // Send message (Twurple handles rate limiting)
      await client.say(channel, message);

      return { ok: true, messageId };
    } catch (error) {
      this.logger.error(
        `Failed to send message: ${error instanceof Error ? error.message : String(error)}`,
      );
      return {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Generate a unique key for an account
   */
  public getAccountKey(account: TwitchAccountConfig): string {
    return `${account.username}:${account.channel}`;
  }

  /**
   * Clear all clients and handlers (for testing)
   */
  _clearForTest(): void {
    this.clients.clear();
    this.messageHandlers.clear();
  }
}
