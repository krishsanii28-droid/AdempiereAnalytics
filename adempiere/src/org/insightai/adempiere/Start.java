package org.insightai.adempiere;

/**
 * Starts the ADempiere desktop client with the InsightAI option on its Performance tab.
 *
 * RUN_Adempiere_InsightAI.bat runs this class instead of org.compiere.Adempiere. It only arranges
 * for the option to be added once the main window exists, then hands over to ADempiere's own
 * start-up unchanged. No ADempiere class or file is modified.
 */
public final class Start {
	private Start() {
	}

	public static void main(String[] args) {
		PerformanceTabOption.install();
		org.compiere.Adempiere.main(args);
	}
}
