import java.awt.Graphics2D;
import java.awt.Window;
import java.awt.image.BufferedImage;
import java.io.File;

import javax.imageio.ImageIO;
import javax.swing.JButton;
import javax.swing.JTabbedPane;
import javax.swing.SwingUtilities;

import org.compiere.apps.AMenu;
import org.compiere.apps.form.FormFrame;
import org.insightai.adempiere.InsightAIForm;
import org.insightai.adempiere.PerformanceTabOption;
import org.insightai.adempiere.Start;

/**
 * Starts the real ADempiere desktop client the way RUN_Adempiere_InsightAI.bat does and checks the
 * InsightAI option on the Performance tab. It needs a property file with AutoLogin switched on so
 * the login dialog completes by itself (scripts\test_client.ps1 makes a temporary copy for that).
 *
 * Once the main window is up it saves a picture of it, presses the Open button, waits for the
 * dashboard to load in the InsightAI window, reports what it shows, and exits.
 *
 * Arguments: main-window picture file, "open" or "look" (look = do not press the button)
 */
public class ClientHarness {
	public static void main(final String[] args) throws Exception {
		final String picture = args[0];
		final boolean press = "open".equals(args[1]);
		Thread watcher = new Thread(new Runnable() {
			@Override
			public void run() {
				try {
					watch(picture, press);
				} catch (Throwable t) {
					System.out.println("CLIENT failed: " + t);
				}
				System.exit(0);
			}
		}, "ClientHarness");
		watcher.setDaemon(true);
		watcher.start();
		Start.main(new String[0]);      // ADempiere's login and main window, with the InsightAI option installed
	}

	private static AMenu findMenu() {
		for (Window window : Window.getWindows())
			if (window instanceof AMenu && window.isShowing())
				return (AMenu) window;
		return null;
	}

	private static void watch(final String picture, boolean press) throws Exception {
		AMenu menu = null;
		long deadline = System.currentTimeMillis() + 90000;
		int presses = 0;
		long lastPress = 0;
		while (System.currentTimeMillis() < deadline && (menu == null || !PerformanceTabOption.isChecked(menu))) {
			Thread.sleep(500);
			menu = findMenu();
			// The login dialog comes with the saved user and password filled in: press OK on it,
			// once for the connection page and once for the role page.
			if (menu == null && presses < 6 && System.currentTimeMillis() - lastPress > 4000) {
				for (final Window window : Window.getWindows()) {
					if (window instanceof java.awt.Dialog && window.isShowing()) {
						final JButton ok = findOk((java.awt.Container) window);
						if (ok != null && ok.isEnabled()) {
							presses++;
							lastPress = System.currentTimeMillis();
							System.out.println("LOGIN pressing OK on \"" + ((java.awt.Dialog) window).getTitle() + "\"");
							SwingUtilities.invokeLater(new Runnable() {
								@Override
								public void run() {
									ok.doClick();
								}
							});
						}
					}
				}
			}
		}
		if (menu == null) {
			System.out.println("CLIENT mainWindow=false (login did not complete)");
			return;
		}
		Thread.sleep(1500);
		final AMenu main = menu;
		final String[] report = new String[1];
		final JButton[] button = new JButton[1];
		SwingUtilities.invokeAndWait(new Runnable() {
			@Override
			public void run() {
				button[0] = PerformanceTabOption.findButton(main);
				JTabbedPane tabs = null;
				java.util.ArrayDeque<java.awt.Container> queue = new java.util.ArrayDeque<java.awt.Container>();
				queue.add(main.getContentPane());
				while (!queue.isEmpty() && tabs == null) {
					for (java.awt.Component c : queue.poll().getComponents()) {
						if (c instanceof JTabbedPane) {
							tabs = (JTabbedPane) c;
							break;
						}
						if (c instanceof java.awt.Container)
							queue.add((java.awt.Container) c);
					}
				}
				StringBuilder names = new StringBuilder();
				int tabWithButton = -1;
				for (int i = 0; tabs != null && i < tabs.getTabCount(); i++) {
					names.append(i == 0 ? "" : ", ").append(tabs.getTitleAt(i));
					if (button[0] != null && SwingUtilities.isDescendingFrom(button[0], tabs.getComponentAt(i)))
						tabWithButton = i;
				}
				report[0] = "tabs=[" + names + "] selected=" + (tabs == null ? "?" : tabs.getTitleAt(tabs.getSelectedIndex()))
						+ " optionOnTab=" + (tabWithButton < 0 ? "none" : tabs.getTitleAt(tabWithButton))
						+ " buttonText=" + (button[0] == null ? "none" : button[0].getText())
						+ " buttonVisible=" + (button[0] != null && button[0].isShowing());
				try {
					BufferedImage image = new BufferedImage(main.getWidth(), main.getHeight(), BufferedImage.TYPE_INT_RGB);
					Graphics2D g = image.createGraphics();
					main.paint(g);
					g.dispose();
					ImageIO.write(image, "png", new File(picture));
				} catch (Exception e) {
					report[0] += " pictureFailed=" + e;
				}
			}
		});
		System.out.println("CLIENT mainWindow=true title=" + main.getTitle() + " " + report[0]);
		if (button[0] == null || !press)
			return;

		SwingUtilities.invokeAndWait(new Runnable() {
			@Override
			public void run() {
				button[0].doClick();
			}
		});
		InsightAIForm form = null;
		deadline = System.currentTimeMillis() + 30000;
		while (System.currentTimeMillis() < deadline && (form == null || !form.isPageLoaded())) {
			Thread.sleep(400);
			FormFrame frame = PerformanceTabOption.getOpenFrame();
			if (frame != null && frame.getFormPanel() instanceof InsightAIForm)
				form = (InsightAIForm) frame.getFormPanel();
		}
		if (form == null) {
			System.out.println("WINDOW opened=false");
			return;
		}
		Thread.sleep(6000);
		String seen = form.isPageLoaded() ? form.evaluate(
				"JSON.stringify({who: document.getElementById('who').textContent,"
				+ " organisations: document.getElementById('f-org').options.length - 1,"
				+ " kpiCards: document.querySelectorAll('.kpi').length, charts: document.querySelectorAll('.js-plotly-plot').length})")
				: form.getStatusText();
		System.out.println("WINDOW opened=true loaded=" + form.isPageLoaded() + " seen=" + seen);
	}

	private static JButton findOk(java.awt.Container parent) {
		for (java.awt.Component child : parent.getComponents()) {
			if (child instanceof JButton && "Ok".equalsIgnoreCase(((JButton) child).getActionCommand()))
				return (JButton) child;
			if (child instanceof java.awt.Container) {
				JButton found = findOk((java.awt.Container) child);
				if (found != null)
					return found;
			}
		}
		return null;
	}

}
