import java.util.Properties;

import org.adempiere.pipo.PackOut;
import org.compiere.Adempiere;
import org.compiere.model.MPInstance;
import org.compiere.model.X_AD_Package_Exp;
import org.compiere.model.X_AD_Package_Exp_Detail;
import org.compiere.process.ProcessInfo;
import org.compiere.util.DB;
import org.compiere.util.Env;

/**
 * Exports the InsightAI dictionary records as a 2Pack, using ADempiere's own PackOut process.
 * It does what the PackOut window does: defines a package with three details (entity type,
 * process, menu) and runs the export. Argument: output directory, ending with a path separator.
 */
public class PackOutHarness {
	static final String PACKAGE_NAME = "InsightAI";

	public static void main(String[] args) throws Exception {
		String directory = args[0];
		if (!Adempiere.startupEnvironment(true))
			throw new IllegalStateException("ADempiere environment did not start");
		Properties ctx = Env.getCtx();
		Env.setContext(ctx, "#AD_Client_ID", 0);
		Env.setContext(ctx, "#AD_Org_ID", 0);
		Env.setContext(ctx, "#AD_User_ID", 100);     // SuperUser
		Env.setContext(ctx, "#AD_Role_ID", 0);       // System Administrator

		int entityTypeId = DB.getSQLValue(null, "SELECT AD_EntityType_ID FROM AD_EntityType WHERE EntityType='INSAI'");
		int processId = DB.getSQLValue(null, "SELECT AD_Process_ID FROM AD_Process WHERE Value='InsightAI_Launch'");
		int menuId = DB.getSQLValue(null, "SELECT AD_Menu_ID FROM AD_Menu WHERE AD_Process_ID=?", processId);
		if (entityTypeId <= 0 || processId <= 0 || menuId <= 0)
			throw new IllegalStateException("InsightAI dictionary records are not installed");

		int existing = DB.getSQLValue(null, "SELECT AD_Package_Exp_ID FROM AD_Package_Exp WHERE Name=?", PACKAGE_NAME);
		X_AD_Package_Exp pack = new X_AD_Package_Exp(ctx, Math.max(existing, 0), null);
		pack.setName(PACKAGE_NAME);
		pack.setDescription("ADempiere InsightAI: entity type, launcher process and menu entry");
		pack.setInstructions("Import with PackIn. Then grant the InsightAI process to the roles that should see it, "
				+ "and install insightai.jar and insightai-launcher.properties (see the InsightAI README).");
		pack.setAD_Package_Type("X");
		pack.setEMail("insightai@localhost");
		pack.setUserName("InsightAI");
		pack.setVersion("1.0");
		pack.setPK_Version("1.0");
		pack.setReleaseNo("all");
		pack.setFile_Directory(directory);
		pack.setProcessing(false);
		pack.saveEx();
		DB.executeUpdateEx("DELETE FROM AD_Package_Exp_Detail WHERE AD_Package_Exp_ID=?", new Object[] { pack.getAD_Package_Exp_ID() }, null);

		addDetail(ctx, pack, 10, "ET", "Entity type INSAI").setAD_EntityType_ID(entityTypeId);
		addDetail(ctx, pack, 20, "P", "Launcher process").setAD_Process_ID(processId);
		addDetail(ctx, pack, 30, "M", "InsightAI menu entry").setAD_Menu_ID(menuId);
		for (X_AD_Package_Exp_Detail detail : details)
			detail.saveEx();

		int packOutProcess = DB.getSQLValue(null, "SELECT AD_Process_ID FROM AD_Process WHERE Value='PackOut'");
		MPInstance instance = new MPInstance(ctx, packOutProcess, pack.getAD_Package_Exp_ID());
		instance.saveEx();
		ProcessInfo info = new ProcessInfo("PackOut", packOutProcess, 0, pack.getAD_Package_Exp_ID());
		info.setAD_PInstance_ID(instance.getAD_PInstance_ID());
		info.setAD_User_ID(100);
		info.setAD_Client_ID(0);
		new PackOut().startProcess(ctx, info, null);
		System.out.println("PACKOUT error=" + info.isError() + " summary=" + info.getSummary());
		System.exit(info.isError() ? 1 : 0);
	}

	private static final java.util.List<X_AD_Package_Exp_Detail> details = new java.util.ArrayList<X_AD_Package_Exp_Detail>();

	private static X_AD_Package_Exp_Detail addDetail(Properties ctx, X_AD_Package_Exp pack, int line, String type, String description) {
		X_AD_Package_Exp_Detail detail = new X_AD_Package_Exp_Detail(ctx, 0, null);
		detail.setAD_Package_Exp_ID(pack.getAD_Package_Exp_ID());
		detail.setLine(line);
		detail.setType(type);
		detail.setDescription(description);
		detail.setProcessing(false);
		details.add(detail);
		return detail;
	}
}
