import java.awt.Container;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.Properties;

import javax.imageio.ImageIO;
import javax.swing.SwingUtilities;

import org.compiere.Adempiere;
import org.compiere.apps.form.FormFrame;
import org.compiere.model.MRole;
import org.compiere.util.DB;
import org.compiere.util.Env;
import org.insightai.adempiere.InsightAIForm;

/**
 * Opens the embedded InsightAI window the way the ADempiere desktop client does: through
 * FormFrame.openForm, which checks the role's form access and creates the form class named in
 * the dictionary. The window is placed off-screen. Once the page has loaded, the harness reads
 * what it shows and saves a picture of the window.
 *
 * Arguments: AD_User_ID AD_Role_ID AD_Client_ID AD_Org_ID picture.png
 */
public class FormHarness {
	public static void main(String[] args) throws Exception {
		final int userId = Integer.parseInt(args[0]), roleId = Integer.parseInt(args[1]);
		final int clientId = Integer.parseInt(args[2]), orgId = Integer.parseInt(args[3]);
		final String picture = args[4];

		if (!Adempiere.startupEnvironment(true))
			throw new IllegalStateException("ADempiere environment did not start");
		Properties ctx = Env.getCtx();
		Env.setContext(ctx, "#AD_Client_ID", clientId);
		Env.setContext(ctx, "#AD_Org_ID", orgId);
		Env.setContext(ctx, "#AD_User_ID", userId);
		Env.setContext(ctx, "#AD_Role_ID", roleId);
		MRole.getDefault(ctx, true);

		final int formId = DB.getSQLValue(null, "SELECT AD_Form_ID FROM AD_Form WHERE Classname='org.insightai.adempiere.InsightAIForm'");

		// What ADempiere's role object says, which is what decides whether the Performance tab shows the option
		System.out.println("ACCESS form=" + (MRole.getDefault(ctx, false).getFormAccess(formId) != null));

		final FormFrame[] frame = new FormFrame[1];
		final boolean[] opened = new boolean[1];
		SwingUtilities.invokeAndWait(new Runnable() {
			@Override
			public void run() {
				// FormFrame positions itself relative to ADempiere's main menu window, which is
				// window number 0. There is no menu here, so an invisible frame stands in for it.
				Env.createWindowNo(new javax.swing.JFrame("InsightAI test"));
				frame[0] = new FormFrame();
				opened[0] = frame[0].openForm(formId);
				if (opened[0]) {
					frame[0].pack();
					frame[0].setSize(1300, 900);
					frame[0].getWindow().setLocation(-8000, 0);
					frame[0].setVisible(true);
				}
			}
		});
		if (!opened[0]) {
			System.out.println("FORM opened=false (ADempiere did not open the form for this role)");
			System.exit(0);
		}

		InsightAIForm form = (InsightAIForm) frame[0].getFormPanel();
		long deadline = System.currentTimeMillis() + 15000;
		while (!form.isPageLoaded() && System.currentTimeMillis() < deadline)
			Thread.sleep(250);
		Thread.sleep(6000);        // let the page fetch its data and draw the charts

		String seen = form.isPageLoaded() ? form.evaluate(
				"JSON.stringify({who: document.getElementById('who').textContent,"
				+ " organisations: Array.prototype.slice.call(document.getElementById('f-org').options).map(function(o){return o.textContent;}),"
				+ " kpiCards: document.querySelectorAll('.kpi').length, charts: document.querySelectorAll('.js-plotly-plot').length,"
				+ " embedded: document.body.classList.contains('embedded'), signOutShown: getComputedStyle(document.querySelector('.who a')).display !== 'none',"
				+ " path: location.pathname + location.search})") : "page did not load";
		System.out.println("FORM opened=true loaded=" + form.isPageLoaded() + " seen=" + seen);
		if (!form.isPageLoaded())
			System.out.println("STATUS " + form.getStatusText());

		SwingUtilities.invokeAndWait(new Runnable() {
			@Override
			public void run() {
				try {
					Container pane = frame[0].getContentPane();
					BufferedImage image = new BufferedImage(pane.getWidth(), pane.getHeight(), BufferedImage.TYPE_INT_RGB);
					Graphics2D g = image.createGraphics();
					pane.paint(g);
					g.dispose();
					ImageIO.write(image, "png", new File(picture));
				} catch (Exception e) {
					System.out.println("FORM picture failed: " + e);
				}
				frame[0].dispose();
			}
		});
		System.exit(0);
	}
}
