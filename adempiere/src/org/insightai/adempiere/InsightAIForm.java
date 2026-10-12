package org.insightai.adempiere;

import java.awt.BorderLayout;
import java.awt.Desktop;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.net.URI;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingConstants;
import javax.swing.SwingWorker;

import org.compiere.apps.form.FormFrame;
import org.compiere.apps.form.FormPanel;
import org.compiere.util.Env;

/**
 * The InsightAI dashboard inside an ADempiere window.
 *
 * An ADempiere form (AD_Form) that signs the current user and role in to the InsightAI service and
 * shows the dashboard in an embedded web view. The web view needs JavaFX, which Oracle JDK 8
 * includes; without it the form explains that and offers to open the dashboard in the browser.
 * Nothing here reads or writes ADempiere business data.
 */
public class InsightAIForm implements FormPanel {

	private FormFrame frame;
	private final JPanel content = new JPanel(new BorderLayout());
	private final JLabel status = new JLabel("", SwingConstants.CENTER);
	private final JButton reload = new JButton("Reload");
	private final JButton inBrowser = new JButton("Open in browser");
	private JComponent web;          // an InsightAIWebPanel, kept as JComponent so this class loads without JavaFX
	private boolean disposed;

	@Override
	public void init(int windowNo, FormFrame formFrame) {
		frame = formFrame;
		JPanel bar = new JPanel(new FlowLayout(FlowLayout.RIGHT, 6, 4));
		bar.add(reload);
		bar.add(inBrowser);
		status.setBorder(BorderFactory.createEmptyBorder(40, 20, 40, 20));
		content.add(bar, BorderLayout.NORTH);
		content.add(status, BorderLayout.CENTER);
		content.setPreferredSize(new Dimension(1280, 800));
		frame.getContentPane().add(content, BorderLayout.CENTER);

		reload.addActionListener(new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent e) {
				open(false);
			}
		});
		inBrowser.addActionListener(new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent e) {
				open(true);
			}
		});

		try {
			web = new InsightAIWebPanel();
		} catch (Throwable noJavaFx) {      // NoClassDefFoundError on a Java runtime without JavaFX
			web = null;
			reload.setEnabled(false);
			status.setText("<html><center>This Java runtime has no JavaFX web view, so InsightAI cannot be shown inside ADempiere."
					+ "<br>Use <b>Open in browser</b> instead.</center></html>");
			return;
		}
		open(false);
	}

	/** Gets a fresh one-time link for the logged-in user and role, then shows it here or in the browser. */
	private void open(final boolean external) {
		final int userId = Env.getAD_User_ID(Env.getCtx());
		final int roleId = Env.getAD_Role_ID(Env.getCtx());
		reload.setEnabled(false);
		inBrowser.setEnabled(false);
		if (!external)
			show(status, "Opening InsightAI…");
		new SwingWorker<String, Void>() {       // the service call must not block the ADempiere window
			@Override
			protected String doInBackground() throws Exception {
				return InsightAILauncher.requestLaunchUrl(userId, roleId, !external);
			}

			@Override
			protected void done() {
				if (disposed)
					return;
				reload.setEnabled(web != null);
				inBrowser.setEnabled(true);
				try {
					String url = get();
					if (external) {
						Desktop.getDesktop().browse(new URI(url));
					} else {
						((InsightAIWebPanel) web).load(url);
						show(web, null);
					}
				} catch (Exception e) {
					Throwable cause = e.getCause() != null ? e.getCause() : e;
					show(status, "<html><center>" + escape(String.valueOf(cause.getMessage()))
							+ "<br><br>Press <b>Reload</b> to try again.</center></html>");
				}
			}
		}.execute();
	}

	private void show(JComponent component, String text) {
		if (text != null)
			status.setText(text);
		BorderLayout layout = (BorderLayout) content.getLayout();
		if (layout.getLayoutComponent(BorderLayout.CENTER) != component) {
			content.remove(layout.getLayoutComponent(BorderLayout.CENTER));
			content.add(component, BorderLayout.CENTER);
		}
		content.revalidate();
		content.repaint();
	}

	private static String escape(String text) {
		return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}

	/** For tests: the message shown instead of the page, without markup. */
	public String getStatusText() {
		return status.getText().replaceAll("<[^>]+>", " ").replaceAll("\\s+", " ").trim();
	}

	/** For tests: true once the embedded page has finished loading. */
	public boolean isPageLoaded() {
		return web != null && ((InsightAIWebPanel) web).isLoaded();
	}

	/** For tests: runs a script in the embedded page and returns its result as text. */
	public String evaluate(String script) throws Exception {
		return ((InsightAIWebPanel) web).evaluate(script);
	}

	@Override
	public void dispose() {
		disposed = true;
		if (web != null)
			((InsightAIWebPanel) web).close();
		FormFrame closing = frame;      // cleared first: FormFrame.dispose() calls back into this method
		frame = null;
		if (closing != null)
			closing.dispose();
	}
}
