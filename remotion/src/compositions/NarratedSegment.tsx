import {
	AbsoluteFill,
	Audio,
	Sequence,
	interpolate,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import { type Brand, getTheme, layout } from "../lib/theme";

type BulletPart = { text: string; style: "text" | "bold" | "code" };

export type NarratedSegmentProps = {
	brand?: Brand;
	sectionTitle: string;
	sectionNumber: number;
	totalSections: number;
	bullets: (string | BulletPart[])[];
	codeBlock: string | null;
	codeLanguage: string | null;
	codeColumnWidth?: number;
	audioFileName: string | null;
	durationInFrames: number;
	bulletTimings: number[];
};

export const calculateNarratedSegmentMetadata = ({
	props,
}: {
	props: NarratedSegmentProps;
}) => {
	return {
		durationInFrames: props.durationInFrames,
		fps: 30,
		width: 1920,
		height: 1080,
	};
};

/** Single bullet line that fades/slides in at a specific frame. */
const Bullet: React.FC<{
	parts: BulletPart[];
	appearFrame: number;
	color: string;
	accentColor: string;
	codeGreen: string;
	codeBg: string;
	font: string;
	monoFont: string;
	fontSize: number;
	dotSize: number;
	margin: number;
	inlineCodeSize: number;
	codeBorderGlow: string;
}> = ({
	parts,
	appearFrame,
	color,
	accentColor,
	codeGreen,
	codeBg,
	font,
	monoFont,
	fontSize,
	dotSize,
	margin,
	inlineCodeSize,
	codeBorderGlow,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();

	const progress = spring({
		frame: frame - appearFrame,
		fps,
		config: { damping: 14, mass: 0.6 },
	});
	const opacity = interpolate(frame - appearFrame, [0, 10], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<div
			style={{
				display: "flex",
				alignItems: "baseline",
				gap: 14,
				opacity,
				transform: `translateX(${interpolate(progress, [0, 1], [-20, 0])}px)`,
				marginBottom: margin,
			}}
		>
			<span
				style={{
					color: accentColor,
					fontSize: dotSize,
					flexShrink: 0,
					fontFamily: monoFont,
				}}
			>
				&#x25B8;
			</span>
			<span
				style={{
					fontSize,
					fontFamily: font,
					color,
					lineHeight: 1.4,
					textWrap: "balance" as const,
				}}
			>
				{parts.map((part, i) => {
					if (part.style === "bold") {
						return (
							<span key={i} style={{ fontWeight: "bold", color: accentColor }}>
								{part.text}
							</span>
						);
					}
					if (part.style === "code") {
						return (
							<span
								key={i}
								style={{
									fontFamily: monoFont,
									backgroundColor: codeBg,
									color: codeGreen,
									padding: "2px 8px",
									borderRadius: 4,
									fontSize: inlineCodeSize,
									whiteSpace: "nowrap" as const,
									boxShadow: codeBorderGlow,
								}}
							>
								{part.text}
							</span>
						);
					}
					return <span key={i}>{part.text}</span>;
				})}
			</span>
		</div>
	);
};

/** Code block with language badge and refined styling. */
const CodeBlock: React.FC<{
	code: string;
	language: string | null;
	appearFrame: number;
	codeBg: string;
	codeColor: string;
	font: string;
	borderColor: string;
	accentColor: string;
	fontSize: number;
	cardShadow: string;
	codeBorderGlow: string;
}> = ({
	code,
	language,
	appearFrame,
	codeBg,
	codeColor,
	font,
	borderColor,
	accentColor,
	fontSize,
	cardShadow,
	codeBorderGlow,
}) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(frame - appearFrame, [0, 20], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const lines = code.split("\n").slice(0, 14);
	const gutterWidth = String(lines.length).length;

	return (
		<div
			style={{
				opacity,
				backgroundColor: codeBg,
				borderRadius: 12,
				padding: "0 24px 16px 24px",
				border: `1px solid ${borderColor}`,
				overflow: "hidden",
				width: "fit-content",
				minWidth: 300,
				minHeight: 0,
				maxHeight: 900,
				boxShadow: `${cardShadow}, ${codeBorderGlow}`,
			}}
		>
			{/* Language badge */}
			{language && (
				<div
					style={{
						fontFamily: font,
						fontSize: 13,
						color: accentColor,
						letterSpacing: 1.5,
						textTransform: "uppercase",
						padding: "10px 0 8px 0",
						borderBottom: `1px solid ${borderColor}`,
						marginBottom: 10,
						fontWeight: 700,
					}}
				>
					{language}
				</div>
			)}

			{lines.map((line, i) => (
				<div
					key={`${i}-${line.slice(0, 20)}`}
					style={{
						fontFamily: font,
						fontSize,
						lineHeight: 1.5,
						whiteSpace: "pre",
						display: "flex",
					}}
				>
					{/* Line number */}
					<span
						style={{
							color: borderColor,
							width: `${gutterWidth + 1}ch`,
							textAlign: "right",
							marginRight: "1.5ch",
							flexShrink: 0,
							userSelect: "none",
							opacity: 0.6,
						}}
					>
						{i + 1}
					</span>
					<span style={{ color: codeColor }}>{line || "\u00A0"}</span>
				</div>
			))}
		</div>
	);
};

export const NarratedSegment: React.FC<NarratedSegmentProps> = ({
	brand = "turtlewolfe",
	sectionTitle,
	sectionNumber,
	totalSections,
	bullets,
	codeBlock,
	codeLanguage,
	codeColumnWidth: pipelineCodeWidth,
	audioFileName,
	durationInFrames: totalFrames,
	bulletTimings,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const { colors, fonts, effects, branding } = getTheme(brand);

	// ── Adaptive sizing: fill available space ────────────────────────
	const hasSidebar = Boolean(codeBlock);
	const availableWidth = 1920 - 2 * layout.padding;
	const availableHeight = 1080 - 100 - 48 - 80;

	// Code column width: use pipeline-calculated value, fall back to estimation for Studio preview
	let codeColumnWidth = 0;
	if (codeBlock) {
		if (pipelineCodeWidth && pipelineCodeWidth > 0) {
			codeColumnWidth = Math.min(pipelineCodeWidth, availableWidth * 0.45);
		} else {
			const maxLineLen = codeBlock
				.split("\n")
				.slice(0, 14)
				.reduce((max, line) => Math.max(max, line.length), 0);
			const estCharWidth = 22 * 0.6;
			codeColumnWidth = Math.min(
				maxLineLen * estCharWidth + 50,
				availableWidth * 0.45,
			);
		}
	}
	const bulletColumnWidth =
		availableWidth - (hasSidebar ? codeColumnWidth + 32 : 0);

	// Iteratively find the largest font that fits, clamped 22–36px.
	const DOT_GAP = 40;
	const PROP_RATIO = 0.55;
	const BOLD_RATIO = 0.57;
	const MONO_RATIO = 0.6;
	const CODE_PAD = 16;

	let bulletFontSize = 22;
	for (let fs = 36; fs >= 22; fs--) {
		const textWidth = bulletColumnWidth - DOT_GAP;
		const codeFs = Math.min(Math.max(fs - 2, 16), 22);
		const lines = bullets.reduce((sum, b) => {
			let px: number;
			if (typeof b === "string") {
				px = b.length * fs * PROP_RATIO;
			} else {
				px = b.reduce((w, part) => {
					if (part.style === "code")
						return w + part.text.length * codeFs * MONO_RATIO + CODE_PAD;
					if (part.style === "bold")
						return w + part.text.length * fs * BOLD_RATIO;
					return w + part.text.length * fs * PROP_RATIO;
				}, 0);
			}
			return sum + Math.max(1, Math.ceil(px / textWidth));
		}, 0);
		const height = lines * fs * 1.4 + (bullets.length - 1) * (fs < 26 ? 6 : 10);
		if (height <= availableHeight) {
			bulletFontSize = fs;
			break;
		}
	}
	const bulletDotSize = bulletFontSize - 2;
	const bulletMargin = bulletFontSize < 26 ? 6 : 10;
	const inlineCodeSize = bulletFontSize - 2;
	const titleSize = 44;
	const codeFontSize = Math.min(Math.max(bulletFontSize - 4, 16), 22);

	// ── Timing ────────────────────────────────────────────────────────
	const timings =
		bulletTimings.length === bullets.length
			? bulletTimings
			: bullets.map((_, i) => {
					const usable = totalFrames * 0.6;
					return Math.round(
						30 + (i / Math.max(bullets.length - 1, 1)) * usable,
					);
				});

	const lastBulletFrame = timings.length > 0 ? timings[timings.length - 1] : 30;
	const codeAppearFrame = lastBulletFrame + 30;

	// ── Animations ────────────────────────────────────────────────────
	const headerProgress = spring({
		frame,
		fps,
		config: { damping: 14, mass: 0.8 },
	});
	const headerOpacity = interpolate(frame, [0, 15], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const titleProgress = spring({
		frame: frame - 10,
		fps,
		config: { damping: 12 },
	});

	const underlineWidth = interpolate(frame, [15, 45], [0, 700], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const fadeOut = interpolate(frame, [totalFrames - 30, totalFrames], [1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<AbsoluteFill
			style={{ background: effects.bgGradient, opacity: fadeOut }}
		>
			{/* Audio narration */}
			{audioFileName && (
				<Sequence from={30}>
					<Audio src={staticFile(audioFileName)} />
				</Sequence>
			)}

			{/* Header bar with accent bottom border */}
			<div
				style={{
					position: "absolute",
					top: 0,
					left: 0,
					right: 0,
					height: 72,
					backgroundColor: colors.bgCard,
					display: "flex",
					justifyContent: "space-between",
					alignItems: "center",
					paddingLeft: layout.padding,
					paddingRight: layout.padding,
					opacity: headerOpacity,
					transform: `translateY(${interpolate(headerProgress, [0, 1], [-72, 0])}px)`,
					borderBottom: `2px solid ${colors.accentDim}`,
					boxShadow: effects.accentGlow,
				}}
			>
				<span
					style={{
						fontSize: 24,
						fontFamily: fonts.mono,
						color: colors.textMuted,
						letterSpacing: 1,
					}}
				>
					Section {sectionNumber} of {totalSections}
				</span>
				<span
					style={{
						fontSize: 24,
						fontFamily: fonts.display,
						color: colors.accent,
						fontWeight: 700,
						letterSpacing: 2,
						textTransform: "uppercase",
					}}
				>
					{branding.name}
				</span>
			</div>

			{/* Main content area */}
			<div
				style={{
					position: "absolute",
					top: 100,
					left: layout.padding,
					right: layout.padding,
					bottom: 48,
					display: "flex",
					flexDirection: "column",
					minHeight: 0,
					overflow: "hidden",
				}}
			>
				{/* Section title */}
				<div
					style={{
						opacity: interpolate(titleProgress, [0, 1], [0, 1]),
						transform: `translateY(${interpolate(titleProgress, [0, 1], [15, 0])}px)`,
						marginBottom: 4,
					}}
				>
					<div
						style={{
							fontSize: titleSize,
							fontWeight: 800,
							fontFamily: fonts.heading,
							color: colors.accent,
							lineHeight: 1.2,
							textShadow: effects.accentTextShadow,
							letterSpacing: -0.5,
						}}
					>
						{sectionTitle}
					</div>
					{/* Gradient underline */}
					<div
						style={{
							height: 4,
							width: underlineWidth,
							background: `linear-gradient(90deg, ${colors.accent}, ${colors.accentDim}, transparent)`,
							borderRadius: 2,
							marginTop: 6,
						}}
					/>
				</div>

				{/* Bullets + code split */}
				<div
					style={{
						flex: 1,
						display: "flex",
						flexDirection: codeBlock ? "row" : "column",
						gap: 32,
						marginTop: 12,
						minHeight: 0,
						overflow: "hidden",
					}}
				>
					{/* Bullets column */}
					<div style={{ flex: 1, overflow: "hidden" }}>
						{bullets.map((bullet, i) => {
							const parts: BulletPart[] =
								typeof bullet === "string"
									? [{ text: bullet, style: "text" }]
									: bullet;
							return (
								<Bullet
									key={`b-${i}`}
									parts={parts}
									appearFrame={timings[i] ?? 30}
									color={colors.text}
									accentColor={colors.accent}
									codeGreen={colors.codeGreen}
									codeBg={colors.codeBg}
									font={fonts.heading}
									monoFont={fonts.mono}
									fontSize={bulletFontSize}
									dotSize={bulletDotSize}
									margin={bulletMargin}
									inlineCodeSize={inlineCodeSize}
									codeBorderGlow={effects.codeBorderGlow}
								/>
							);
						})}
					</div>

					{/* Code column */}
					{codeBlock && (
						<div
							style={{
								flex: `0 0 ${codeColumnWidth}px`,
								maxWidth: "45%",
								display: "flex",
								alignItems: "flex-start",
								overflow: "hidden",
							}}
						>
							<CodeBlock
								code={codeBlock}
								language={codeLanguage}
								appearFrame={codeAppearFrame}
								codeBg={colors.codeBg}
								codeColor={colors.codeGreen}
								font={fonts.mono}
								borderColor={colors.accentDim}
								accentColor={colors.accent}
								fontSize={codeFontSize}
								cardShadow={effects.cardShadow}
								codeBorderGlow={effects.codeBorderGlow}
							/>
						</div>
					)}
				</div>
			</div>

			{/* Channel watermark */}
			<div
				style={{
					position: "absolute",
					bottom: 24,
					right: layout.padding,
					fontSize: 20,
					fontFamily: fonts.mono,
					color: colors.textMuted,
					opacity: 0.5,
					letterSpacing: 1,
				}}
			>
				{branding.channel}
			</div>
		</AbsoluteFill>
	);
};
