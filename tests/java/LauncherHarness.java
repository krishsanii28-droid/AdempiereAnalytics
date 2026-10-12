import java.util.Properties;

import org.compiere.Adempiere;
import org.compiere.model.MPInstance;
import org.compiere.process.ProcessInfo;
import org.compiere.util.DB;
import org.compiere.util.Env;
import org.insightai.adempiere.InsightAILauncher;

/**
 * Runs the InsightAI launcher process the way the desktop client does, but without the GUI:
 * starts the ADempiere environment, sets the login context, creates a process instance and
 * executes the process class. Used to test the hand-off for different users and roles.
 *
 * Run with -Dinsightai.nobrowser=true so the launch link is printed instead of opened.
 * Arguments: AD_User_ID AD_Role_ID AD_Client_ID AD_Org_ID
 */
public class LauncherHarness {
	public static void main(String[] args) throws Exception {
		int userId = Integer.parseInt(args[0]), roleId = Integer.parseInt(args[1]);
		int clientId = Integer.parseInt(args[2]), orgId = Integer.parseInt(args[3]);

		// Client mode, as in the desktop client. startup(true) alone stops before the database
		// connection (the GUI connects at login), so the environment is started explicitly.
		if (!Adempiere.startupEnvironment(true))
			throw new IllegalStateException("ADempiere environment did not start");
		Properties ctx = Env.getCtx();
		Env.setContext(ctx, "#AD_Client_ID", clientId);
		Env.setContext(ctx, "#AD_Org_ID", orgId);
		Env.setContext(ctx, "#AD_User_ID", userId);
		Env.setContext(ctx, "#AD_Role_ID", roleId);

		int processId = DB.getSQLValue(null, "SELECT AD_Process_ID FROM AD_Process WHERE Value='InsightAI_Launch'");
		String className = DB.getSQLValueString(null, "SELECT Classname FROM AD_Process WHERE AD_Process_ID=?", processId);
		MPInstance instance = new MPInstance(ctx, processId, 0);
		instance.saveEx();

		ProcessInfo info = new ProcessInfo("InsightAI", processId);
		info.setAD_PInstance_ID(instance.getAD_PInstance_ID());
		info.setAD_User_ID(userId);
		info.setAD_Client_ID(clientId);
		info.setClassName(className);

		// Load the class by the name stored in the dictionary, as ADempiere does
		InsightAILauncher process = (InsightAILauncher) Class.forName(className).getDeclaredConstructor().newInstance();
		process.startProcess(ctx, info, null);
		System.out.println("HARNESS error=" + info.isError() + " summary=" + info.getSummary());
		System.exit(0);
	}
}
