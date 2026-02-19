import {
	AbsoluteFill,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import { type Brand, getTheme, layout } from "../lib/theme";

type Props = {
	brand?: Brand;
	currentEpisodeTitle: string;
	nextEpisodeTitle?: string;
	nextEpisodeDate?: string;
	nextEpisodeTopic?: string;
	callToAction?: string;
};

export const EpisodeOutro: React.FC<Props> = ({
	brand = "turtlewolfe",
	currentEpisodeTitle,
	nextEpisodeTitle,
	nextEpisodeDate,
	nextEpisodeTopic,
	callToAction = "See you next time!",
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const { colors, fonts, effects, branding } = getTheme(brand);

	const hasNextEpisode = nextEpisodeTitle && nextEpisodeDate;
	const isUpNext = nextEpisodeTitle && !nextEpisodeDate;

	// ── "Up Next" mode: short 5-sec transition between series episodes ──
	if (isUpNext) {
		const upNextHeadingOpacity = interpolate(frame, [0, 15], [0, 1], {
			extrapolateLeft: "clamp",
			extrapolateRight: "clamp",
		});
		const upNextTitleProgress = spring({
			frame: frame - 15,
			fps,
			config: { damping: 14, mass: 0.6 },
		});
		const upNextFadeOut = interpolate(frame, [120, 150], [1, 0], {
			extrapolateLeft: "clamp",
			extrapolateRight: "clamp",
		});

		// Divider between heading and title
		const dividerWidth = interpolate(frame, [10, 40], [0, 200], {
			extrapolateLeft: "clamp",
			extrapolateRight: "clamp",
		});

		return (
			<AbsoluteFill
				style={{ background: effects.bgGradient, opacity: upNextFadeOut }}
			>
				<div
					style={{
						position: "absolute",
						top: "38%",
						left: "50%",
						transform: "translate(-50%, -50%)",
						textAlign: "center",
					}}
				>
					<div
						style={{
							fontSize: 32,
							color: colors.textMuted,
							fontFamily: fonts.display,
							textTransform: "uppercase",
							letterSpacing: 6,
							opacity: upNextHeadingOpacity,
							marginBottom: 20,
						}}
					>
						Up Next
					</div>
					<div
						style={{
							width: dividerWidth,
							height: 1,
							background: `linear-gradient(90deg, transparent, ${colors.accent}, transparent)`,
							margin: "0 auto 24px auto",
						}}
					/>
					<div
						style={{
							fontSize: 64,
							fontWeight: 800,
							color: colors.accent,
							fontFamily: fonts.heading,
							opacity: interpolate(upNextTitleProgress, [0, 1], [0, 1]),
							transform: `translateY(${interpolate(upNextTitleProgress, [0, 1], [20, 0])}px)`,
							textShadow: effects.accentTextShadow,
						}}
					>
						{nextEpisodeTitle}
					</div>
				</div>
				<div
					style={{
						position: "absolute",
						bottom: 40,
						left: "50%",
						transform: "translateX(-50%)",
						fontSize: 22,
						color: colors.textMuted,
						fontFamily: fonts.mono,
						opacity: 0.5,
						letterSpacing: 1,
					}}
				>
					{branding.channel}
				</div>
			</AbsoluteFill>
		);
	}

	// ── Full outro or generic CTA ──────────────────────────────────────

	const thanksOpacity = interpolate(frame, [0, 20, 70, 90], [0, 1, 1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const currentTitleOpacity = interpolate(
		frame,
		[0, 10, 60, 80],
		[1, 1, 1, 0],
		{
			extrapolateLeft: "clamp",
			extrapolateRight: "clamp",
		},
	);
	const currentTitleY = interpolate(frame, [60, 90], [0, -30], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const nextHeadingOpacity = interpolate(frame, [90, 120], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const nextHeadingScale = spring({
		frame: frame - 90,
		fps,
		config: { damping: 12, mass: 0.6 },
	});

	const cardOpacity = interpolate(frame, [140, 170], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const cardY = spring({
		frame: frame - 140,
		fps,
		config: { damping: 14 },
	});

	const fadeOut = interpolate(frame, [260, 290], [1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const ctaOpacity = interpolate(frame, [150, 180, 260, 290], [0, 1, 1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<AbsoluteFill
			style={{ background: effects.bgGradient, opacity: fadeOut }}
		>
			{/* Phase 1: Thanks for watching + current episode title */}
			<div
				style={{
					position: "absolute",
					top: "35%",
					left: "50%",
					transform: `translate(-50%, -50%) translateY(${currentTitleY}px)`,
					textAlign: "center",
				}}
			>
				<div
					style={{
						fontSize: 36,
						color: colors.textMuted,
						fontFamily: fonts.mono,
						opacity: thanksOpacity,
						marginBottom: 16,
						letterSpacing: 1,
					}}
				>
					Thanks for watching!
				</div>
				<div
					style={{
						fontSize: 56,
						fontWeight: 700,
						color: colors.text,
						fontFamily: fonts.heading,
						opacity: currentTitleOpacity,
						fontStyle: "italic",
					}}
				>
					{currentEpisodeTitle}
				</div>
			</div>

			{hasNextEpisode ? (
				<>
					{/* Phase 2: "Next Episode" heading */}
					<div
						style={{
							position: "absolute",
							top: "30%",
							left: "50%",
							transform: `translate(-50%, -50%) scale(${interpolate(nextHeadingScale, [0, 1], [0.8, 1])})`,
							opacity: nextHeadingOpacity,
							textAlign: "center",
						}}
					>
						<div
							style={{
								fontSize: 32,
								color: colors.accent,
								fontFamily: fonts.display,
								textTransform: "uppercase",
								letterSpacing: 6,
							}}
						>
							Next Episode
						</div>
					</div>

					{/* Phase 3: Next episode card */}
					<div
						style={{
							position: "absolute",
							top: "55%",
							left: "50%",
							transform: `translate(-50%, -50%) translateY(${interpolate(cardY, [0, 1], [40, 0])}px)`,
							opacity: cardOpacity,
							textAlign: "center",
							padding: layout.padding,
							backgroundColor: colors.bgCard,
							borderRadius: 16,
							minWidth: 600,
							boxShadow: effects.cardShadow,
							border: `1px solid ${colors.accentDim}`,
						}}
					>
						<div
							style={{
								fontSize: 64,
								fontWeight: 800,
								color: colors.accent,
								fontFamily: fonts.heading,
								marginBottom: 16,
								textShadow: effects.accentTextShadow,
							}}
						>
							{nextEpisodeTitle}
						</div>
						{nextEpisodeTopic && (
							<div
								style={{
									fontSize: 32,
									color: colors.text,
									fontFamily: fonts.heading,
									fontStyle: "italic",
									marginBottom: 24,
								}}
							>
								{nextEpisodeTopic}
							</div>
						)}
						<div
							style={{
								display: "inline-block",
								backgroundColor: colors.accent,
								color: colors.bg,
								padding: "12px 32px",
								borderRadius: 12,
								fontSize: 28,
								fontFamily: fonts.mono,
								fontWeight: 600,
								boxShadow: effects.accentGlow,
								letterSpacing: 1,
							}}
						>
							{nextEpisodeDate}
						</div>
					</div>
				</>
			) : (
				/* No next episode: show generic CTA */
				<div
					style={{
						position: "absolute",
						top: "60%",
						left: "50%",
						transform: "translate(-50%, -50%)",
						opacity: ctaOpacity,
						textAlign: "center",
					}}
				>
					<div
						style={{
							fontSize: 48,
							fontWeight: 700,
							color: colors.accent,
							fontFamily: fonts.heading,
							marginBottom: 24,
							textShadow: effects.accentTextShadow,
						}}
					>
						{callToAction}
					</div>
					<div
						style={{
							fontSize: 28,
							color: colors.textMuted,
							fontFamily: fonts.mono,
							letterSpacing: 1,
						}}
					>
						Follow for more episodes
					</div>
				</div>
			)}

			{/* Channel watermark */}
			<div
				style={{
					position: "absolute",
					bottom: 40,
					left: "50%",
					transform: "translateX(-50%)",
					fontSize: 22,
					color: colors.textMuted,
					fontFamily: fonts.mono,
					opacity: 0.5,
					letterSpacing: 1,
				}}
			>
				{branding.channel}
			</div>
		</AbsoluteFill>
	);
};
