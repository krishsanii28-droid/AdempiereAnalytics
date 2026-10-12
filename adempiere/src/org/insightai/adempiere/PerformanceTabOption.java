package org.insightai.adempiere;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Container;
import java.awt.Window;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JPanel;
import javax.swing.JTabbedPane;
import javax.swing.SwingUtilities;

import org.adempiere.apps.graph.PAPanel;
import org.compiere.apps.AEnv;
import org.compiere.apps.AMenu;
import org.compiere.apps.WindowManager;
import org.compiere.apps.form.FormFrame;
import org.compiere.model.MRole;
import org.compiere.util.DB;
import org.compiere.util.Env;

/**
 * Adds an "InsightAI" strip with an Open button to the top of the Performance tab of ADempiere's
 * main window, for roles that have been granted the InsightAI form.
 *
 * ADempiere offers no extension point for that tab: its own dashboard content can link only to
 * standard windows. So this watches for the main window to appear after login and wraps the tab's
 * existing panel, leaving the panel itself as it is. If anything here fails, the Performance tab
 * is simply left unchanged.
 */
public final class PerformanceTabOption {

	/** Name of the button, so tests can find it. */
	public static final String BUTTON_NAME = "insightai.open";
	static final String FORM_CLASSNAME = "org.insightai.adempiere.InsightAIForm";
	private static final String DONE = "insightai.performanceTabOption";
	private static volatile boolean installed;
	private static volatile FormFrame openFrame;       // the InsightAI window opened from here, if still open

	private PerformanceTabOption() {
	}

	/** Starts watching for ADempiere's main window. Safe to call more than once. */
	public static synchronized void install() {
		if (installed)
			return;
		installed = true;
		Thread watcher = new Thread(new Runnable() {
			@Override
			public void run() {
				// Keeps running: logging out and in again creates a new main window
				while (true) {
					try {
						Thread.sleep(700);
						SwingUtilities.invokeLater(new Runnable() {
							@Override
							public void run() {
								addToOpenMenus();
							}
						});
					} catch (InterruptedException e) {
						return;
					}
				}
			}
		}, "InsightAI-PerformanceTab");
		watcher.setDaemon(true);
		watcher.start();
	}

	private static void addToOpenMenus() {
		for (Window window : Window.getWindows()) {
			if (!(window instanceof AMenu) || !window.isShowing())
				continue;
			AMenu menu = (AMenu) window;
			if (menu.getRootPane().getClientProperty(DONE) != null)
				continue;
			menu.getRootPane().putClientProperty(DONE, Boolean.TRUE);      // one attempt per main window
			try {
				add(menu);
			} catch (Throwable problem) {       // never let this disturb ADempiere's main window
				System.err.println("InsightAI: could not add the option to the Performance tab: " + problem);
			}
		}
	}

	private static void add(final AMenu menu) {
		final int formId = DB.getSQLValue(null, "SELECT AD_Form_ID FROM AD_Form WHERE Classname=? AND IsActive='Y'", FORM_CLASSNAME);
		if (formId <= 0)
			return;                                                         // InsightAI is not installed in this database
		if (MRole.getDefault(Env.getCtx(), false).getFormAccess(formId) == null)
			return;                                                         // this role has not been granted InsightAI

		JTabbedPane tabs = find(menu.getContentPane(), JTabbedPane.class);
		if (tabs == null)
			return;

		JButton open = new JButton("Open InsightAI dashboard");
		open.setName(BUTTON_NAME);
		open.addActionListener(new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent e) {
				openDashboard(menu, formId);
			}
		});
		// ADempiere's main window is narrow, so the option is one full-width button; the detail is in the tooltip
		open.setToolTipText("Sales, receivables and stock analytics, demand forecast, and questions in plain English");
		JPanel strip = new JPanel(new BorderLayout());
		strip.setBorder(BorderFactory.createCompoundBorder(
				BorderFactory.createMatteBorder(0, 0, 1, 0, Color.GRAY), BorderFactory.createEmptyBorder(6, 8, 6, 8)));
		strip.add(open, BorderLayout.CENTER);

		// The Performance tab is the one holding ADempiere's PAPanel
		for (int i = 0; i < tabs.getTabCount(); i++) {
			Component existing = tabs.getComponentAt(i);
			if (existing instanceof PAPanel || (existing instanceof Container && find((Container) existing, PAPanel.class) != null)) {
				JPanel wrapper = new JPanel(new BorderLayout());
				wrapper.add(strip, BorderLayout.NORTH);
				tabs.setComponentAt(i, wrapper);         // detaches the existing panel from the tab ...
				wrapper.add(existing, BorderLayout.CENTER);   // ... which is then shown below the strip, unchanged
				wrapper.revalidate();
				return;
			}
		}
		// A user with no performance goals has no Performance tab: give the option a first tab of its own
		JPanel own = new JPanel(new BorderLayout());
		own.add(strip, BorderLayout.NORTH);
		tabs.insertTab("InsightAI", null, own, "InsightAI analytics dashboard", 0);
	}

	/** Opens the InsightAI window the way ADempiere's menu opens a form. */
	static void openDashboard(AMenu menu, int formId) {
		FormFrame already = openFrame;
		if (already != null && already.getWindow() != null && already.getWindow().isDisplayable()) {
			already.toFront();                       // one InsightAI window at a time
			return;
		}
		FormFrame frame = new FormFrame();
		if (!frame.openForm(formId)) {
			frame.dispose();
			return;
		}
		WindowManager windows = menu.getWindowManager();
		windows.add(frame.getCFrame());              // lists it in ADempiere's Window menu
		AEnv.showMaximized(frame.getCFrame());
		openFrame = frame;
	}

	/** For tests: the InsightAI window last opened from the Performance tab, or null. */
	public static FormFrame getOpenFrame() {
		return openFrame;
	}

	@SuppressWarnings("unchecked")
	private static <T> T find(Container parent, Class<T> type) {
		for (Component child : parent.getComponents()) {
			if (type.isInstance(child))
				return (T) child;
			if (child instanceof Container) {
				T found = find((Container) child, type);
				if (found != null)
					return found;
			}
		}
		return null;
	}

	/** For tests: the Open button on this main window, or null if the option was not added. */
	public static JButton findButton(AMenu menu) {
		return findNamed(menu.getContentPane(), BUTTON_NAME);
	}

	private static JButton findNamed(Container parent, String name) {
		for (Component child : parent.getComponents()) {
			if (child instanceof JButton && name.equals(child.getName()))
				return (JButton) child;
			if (child instanceof Container) {
				JButton found = findNamed((Container) child, name);
				if (found != null)
					return found;
			}
		}
		return null;
	}

	/** For tests: true once this main window has been looked at, whether or not the option was added. */
	public static boolean isChecked(AMenu menu) {
		return ((JComponent) menu.getRootPane()).getClientProperty(DONE) != null;
	}
}
